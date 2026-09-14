"""Live delivery through the installed desktop runtimes and the cloud sessions API.

Codex desktop IPC uses length-prefixed JSON requests. Claude's registered peer
socket accepts authenticated newline-delimited JSON. A Claude session that is
not on this machine -- one running on Anthropic's machines, or bridged from
another computer through Remote Control -- takes a cross-session event posted
to its cloud record, the same request the CLI's own SendMessage makes. No path
writes a deferred message to disk. A timeout after submission is uncertain,
never a reason to resend through another transport.
"""

import hashlib
import http.client
import json
import os
import re
import socket
import stat
import struct
import sys
import time
import unicodedata
import uuid
from urllib.parse import quote, urlsplit


class DeliveryError(Exception):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


def _owned_path(path, kind):
    info = os.lstat(path)
    valid = stat.S_ISSOCK(info.st_mode) if kind == "socket" else stat.S_ISREG(info.st_mode)
    if not valid or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise DeliveryError(f"{kind} is not a same-user protected {kind}: {path}")


def _verify_peer(sock, expected_pid):
    if sys.platform == "darwin":
        # macOS sys/un.h: SOL_LOCAL = 0, LOCAL_PEERPID = 2.
        pid = sock.getsockopt(0, 2)
    elif sys.platform.startswith("linux"):
        pid, uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise DeliveryError("connected peer is owned by another user")
    else:
        raise DeliveryError("cannot verify the local peer on this platform")
    if pid != expected_pid:
        raise DeliveryError("connected peer is not the process in the session registry")


class CodexIPC:
    """A client of the existing desktop router; does not start another core."""

    def __init__(self, path, timeout=30):
        self.path = path
        self.timeout = timeout
        self.client_id = "initializing-client"
        self.sock = None

    def __enter__(self):
        _owned_path(self.path, "socket")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.settimeout(self.timeout)
            self.sock.connect(self.path)
            result = self.request("initialize", {"clientType": "relay"}, version=0)
            self.client_id = result["result"]["clientId"]
            return self
        except Exception:
            self.sock.close()
            raise

    def __exit__(self, *args):
        self.sock.close()

    def _write(self, packet):
        data = json.dumps(packet, ensure_ascii=False).encode("utf-8")
        self.sock.sendall(struct.pack("<I", len(data)) + data)

    def _read_exact(self, count, deadline):
        data = bytearray()
        while len(data) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("desktop IPC response timed out")
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise EOFError("desktop IPC connection closed")
            data.extend(chunk)
        return data

    def request(self, method, params, *, version, target=None, mutating=False):
        rid = str(uuid.uuid4())
        packet = {"type": "request", "requestId": rid,
                  "sourceClientId": self.client_id, "version": version,
                  "method": method, "params": params,
                  "timeoutMs": int(self.timeout * 1000)}
        if target:
            packet["targetClientId"] = target
        deadline = time.monotonic() + self.timeout
        try:
            self.sock.settimeout(self.timeout)
            self._write(packet)
            while True:
                size, = struct.unpack("<I", self._read_exact(4, deadline))
                if not 0 < size <= 16 * 1024 * 1024:
                    raise ValueError("invalid desktop IPC frame length")
                reply = json.loads(self._read_exact(size, deadline))
                if reply.get("type") == "client-discovery-request":
                    self._write({"type": "client-discovery-response",
                                 "requestId": reply["requestId"],
                                 "response": {"canHandle": False}})
                    continue
                if reply.get("type") != "response" or reply.get("requestId") != rid:
                    continue
                if reply.get("resultType") == "error":
                    detail = reply.get("error", "desktop rejected request")
                    # A router timeout/disconnection can occur after the owner
                    # accepted the request. Never fall back after this result.
                    uncertain = mutating and any(word in detail.lower() for word in
                        ("timeout", "timed out", "disconnected", "outcome-unknown"))
                    raise DeliveryError(detail, uncertain=uncertain)
                if reply.get("resultType") != "success" or reply.get("method") != method:
                    raise ValueError("unexpected desktop IPC response")
                return reply
        except DeliveryError:
            raise
        except (OSError, EOFError, ValueError, KeyError) as exc:
            raise DeliveryError(f"{method}: {exc}", uncertain=mutating) from exc


def send_codex(thread_id, text, codex_home, *, timeout=30):
    """Steer an active task; start a turn only after an explicit idle rejection."""
    message_id = str(uuid.uuid4())
    content = [{"type": "text", "text": text, "text_elements": []}]
    submitted = False
    try:
        with CodexIPC(os.path.join(codex_home, "ipc", "ipc.sock"), timeout) as ipc:
            owner = ipc.request("thread-owner-discovery",
                                {"hostId": "local", "conversationId": thread_id},
                                version=1)["handledByClientId"]
            restore = {"id": message_id, "text": text, "createdAt": int(time.time() * 1000),
                       "context": {"prompt": text, "addedFiles": [], "fileAttachments": [],
                                   "ideContext": None, "imageAttachments": []}}
            try:
                submitted = True
                response = ipc.request("thread-follower-steer-turn",
                    {"conversationId": thread_id, "clientUserMessageId": message_id,
                     "input": content, "restoreMessage": restore, "attachments": []},
                    version=1, target=owner, mutating=True)
                result = response["result"]["result"]
                if not result.get("turnId"):
                    raise DeliveryError("steering response omitted turnId", uncertain=True)
                return {"status": "steered", "turnId": result["turnId"], "messageId": message_id}
            except DeliveryError as exc:
                if exc.uncertain or str(exc) != (
                        f"Cannot steer conversation {thread_id} because its active turn already ended"):
                    raise
            # The owner confirmed that steering added nothing. Inherit the
            # task's saved model, permissions, working directory, and settings.
            response = ipc.request("thread-follower-start-turn",
                {"conversationId": thread_id,
                 "turnStart": {"request": {"threadId": thread_id, "input": content,
                                            "clientUserMessageId": message_id},
                               "context": {"inheritThreadSettings": True}}},
                version=2, target=owner, mutating=True)
            result = response["result"]["result"]
            turn_id = result.get("turn", {}).get("id")
            if not turn_id:
                raise DeliveryError("turn start response omitted turn id", uncertain=True)
            return {"status": "started", "turnId": turn_id, "messageId": message_id}
    except DeliveryError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise DeliveryError(f"Codex desktop delivery failed: {exc}", uncertain=submitted) from exc


def _claude_auth(peer, sessions_root):
    digest = hashlib.sha256(os.path.abspath(peer["socket"]).encode()).hexdigest()
    path = os.path.join(sessions_root, f"{peer['pid']}.{digest}.key")
    _owned_path(path, "file")
    with open(path) as stream:
        token = json.load(stream).get("peerToken")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", token):
        raise DeliveryError("Claude peer authentication key is invalid")
    return {"type": "auth", "token": token}


def send_claude(peer, text, sender, sessions_root, *, timeout=5):
    """Submit to the native peer receiver, whose enqueue callback wakes Claude.

    The receiver records the connecting process as the peer. `from-name` is a
    display label; no Claude process address or verified identity is impersonated.
    The native write protocol has no synchronous read receipt.
    """
    submitted = False
    try:
        os.kill(peer["pid"], 0)
        _owned_path(peer["socket"], "socket")
        auth = _claude_auth(peer, sessions_root)
        name = re.sub(r'["<>\x00-\x1f\x7f]', '', sender or "relay").strip() or "relay"
        # Keep the native provenance wrapper intact when quoting another message.
        body = re.sub(r"<(\/?cross-session-message\b)", r"<\\\1", text, flags=re.I)
        message_id = str(uuid.uuid4())
        packet = {"msgV": 1, "msg_id": message_id, "type": "user", "priority": "next",
                  "message": {"role": "user", "content":
                      f'<cross-session-message from-name="{name}">\n{body}\n</cross-session-message>'}}
        data = b"".join((json.dumps(p, ensure_ascii=False) + "\n").encode()
                        for p in (auth, packet))
        if len(data) > 256 * 1024:
            raise DeliveryError("message exceeds the relay's 256 KiB limit")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(peer["socket"])
            _verify_peer(sock, peer["pid"])
            submitted = True
            sock.sendall(data)
            # Match the macOS native sender: allow its auth/data handlers to run
            # before ending the connection. This is not a polling interval.
            time.sleep(0.15)
            sock.shutdown(socket.SHUT_WR)
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Claude receiver did not close the connection")
                sock.settimeout(remaining)
                if not sock.recv(4096):
                    break
        return {"status": "submitted", "messageId": message_id}
    except DeliveryError:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise DeliveryError(f"Claude peer delivery failed: {exc}", uncertain=submitted) from exc


# --- cloud sessions -----------------------------------------------------------
#
# A cloud record (`cse_…` in the API, `session_…` inside the CLI) fronts every
# session the account can reach through Anthropic's servers: a session running
# on their machines, and any session bridged from a computer through Remote
# Control. The CLI's SendMessage reaches both the same way -- one `type: user`
# event whose text is a `<cross-session-message>` envelope, posted to the
# record's events endpoint -- and the receiving CLI recognises the envelope
# byte for byte, so the attribute order and the escaping below are the
# receiver's grammar, not a style choice.

CLOUD_API = "https://api.anthropic.com"
CLOUD_BETA = "ccr-byoc-2025-07-29"
CLOUD_UA = "claude-code/2.1.270"
CLOUD_MODES = ("bypass", "prompting")
CLOUD_ID_RE = re.compile(r"^(?:bridge:)?(?:cse|session)_([A-Za-z0-9]+)$")
_ENVELOPE_TAG = "cross-session-message"
_ADDRESS_SAFE = re.compile(r"[^A-Za-z0-9:_/.\\-]")


def cloud_ids(any_id):
    """`(cse_id, session_id)` for a cloud session id in any spelling the tree
    meets -- the API's `cse_`, the CLI's `session_`, or a `bridge:` address."""
    m = CLOUD_ID_RE.match((any_id or "").strip())
    if not m:
        raise ValueError(f"not a cloud session id: {any_id!r}")
    return "cse_" + m.group(1), "session_" + m.group(1)


def cloud_address(any_id):
    """The address a Claude caller hands its native SendMessage tool."""
    return "bridge:" + cloud_ids(any_id)[1]


def cloud_name(sender):
    """The `from-name` the receiving CLI will accept: no quotes or angle
    brackets, no control or format characters, at most 64 code points."""
    text = re.sub(r'["<>]', "", sender or "")
    text = "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Zl", "Zp")).strip()
    chars = list(text)
    return "".join(chars[:64]) + "\u2026" if len(chars) > 64 else text


def cloud_envelope(text, sender, mode="bypass", from_address=None):
    """The envelope the CLI's own SendMessage writes for a cloud peer.

    `from` is a reply address (a `bridge:` address of the sending session);
    `from-name` a display label; `from-mode` the sender's permission class,
    which the receiver compares with its own before delivering unasked."""
    if mode not in CLOUD_MODES:
        raise ValueError(f"from-mode must be one of {CLOUD_MODES}")
    attrs = []
    if from_address:
        attrs.append(f'from="{_ADDRESS_SAFE.sub(lambda m: quote(m.group(0), safe=""), from_address)}"')
    name = cloud_name(sender)
    if name:
        attrs.append(f'from-name="{name}"')
    attrs.append(f'from-mode="{mode}"')
    body = re.sub(rf"<(\/?{_ENVELOPE_TAG}\b)", r"<\\\1", text, flags=re.I)
    return f"<{_ENVELOPE_TAG} {' '.join(attrs)}>\n{body}\n</{_ENVELOPE_TAG}>"


def _cloud_refusal(status, data):
    detail = ""
    code = ""
    try:
        parsed = json.loads(data or b"{}")
        err = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(err, dict):
            detail = str(err.get("message") or "")[:200]
            code = str(err.get("resource") or err.get("type") or "")
        elif isinstance(err, str):
            detail = err[:200]
    except ValueError:
        detail = (data or b"")[:200].decode("utf-8", "replace")
    if status == 401:
        return ("auth: the cloud API rejected the token (401). The desktop app's Claude Code "
                "grant is stale; open the Claude app signed in, or run `claude auth login`.")
    if status == 403:
        why = {"untrusted_device": "this device is not enrolled as trusted for that session",
               "session_stale_relogin": "the sign-in behind the token is stale; sign in again"}.get(code)
        return f"auth: refused (403){': ' + why if why else ''}{' \u2014 ' + detail if detail and not why else ''}"
    if status == 404:
        return "no such cloud session (archived, or the id is stale) \u2014 re-run `board`"
    return f"HTTP {status}{': ' + detail if detail else ''}"


def send_cloud(any_id, text, sender, *, token, org_uuid, mode="bypass", from_address=None,
               base_url=CLOUD_API, timeout=10):
    """Post one cross-session message to a cloud record.

    Returns the receipt on 2xx. Anything the server said no to raises a
    certain DeliveryError; a connection that died after the request was on the
    wire raises an uncertain one, because the event may have been accepted."""
    cse_id, session_id = cloud_ids(any_id)
    if not token:
        raise DeliveryError("no cloud grant available; nothing was sent")
    message_id = str(uuid.uuid4())
    payload = {"msgV": 1, "msg_id": message_id, "type": "user",
               "message": {"role": "user", "content": cloud_envelope(text, sender, mode, from_address)},
               "parent_tool_use_id": None, "session_id": session_id, "uuid": str(uuid.uuid4())}
    body = json.dumps({"events": [{"payload": payload}]}, ensure_ascii=False).encode("utf-8")
    if len(body) > 256 * 1024:
        raise DeliveryError("message exceeds the relay's 256 KiB limit")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "anthropic-version": "2023-06-01", "anthropic-client-platform": "claude_code",
               "anthropic-beta": CLOUD_BETA, "User-Agent": CLOUD_UA,
               "Content-Length": str(len(body))}
    if org_uuid:
        headers["x-organization-uuid"] = org_uuid
    url = urlsplit(base_url)
    conn_cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(url.hostname, url.port, timeout=timeout)
    path = f"{url.path.rstrip('/')}/v1/code/sessions/{quote(cse_id, safe='')}/events"
    submitted = False
    try:
        try:
            conn.request("POST", path, body, headers)
        except (OSError, http.client.HTTPException) as exc:
            raise DeliveryError(f"cloud post failed before sending: {exc}") from exc
        submitted = True
        try:
            resp = conn.getresponse()
            data = resp.read()
        except (OSError, http.client.HTTPException) as exc:
            raise DeliveryError(f"no answer from the cloud API after posting: {exc}", uncertain=True) from exc
    finally:
        conn.close()
    if resp.status not in (200, 201, 204):
        raise DeliveryError(_cloud_refusal(resp.status, data), uncertain=submitted and resp.status >= 500)
    receipt = {"status": "posted", "messageId": message_id, "session": cse_id}
    try:
        result = (json.loads(data or b"{}").get("results") or [{}])[0]
        if result.get("sequence_num") is not None:
            receipt["sequenceNum"] = str(result["sequence_num"])
        if result.get("duplicate"):
            receipt["duplicate"] = True
    except (ValueError, AttributeError, IndexError):
        pass
    return receipt
