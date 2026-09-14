"""Live local delivery through the installed desktop runtimes.

Codex desktop IPC uses length-prefixed JSON requests. Claude's registered peer
socket accepts authenticated newline-delimited JSON. Neither path writes a
deferred message to disk. A timeout after submission is uncertain, never a
reason to resend through another transport.
"""

import hashlib
import json
import os
import re
import socket
import stat
import struct
import sys
import time
import uuid


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
