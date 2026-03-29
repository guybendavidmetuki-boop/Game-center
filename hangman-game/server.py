#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import random
import string
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
ROOMS: dict[str, dict[str, Any]] = {}
MAX_WRONG = 6
FINAL_MAP = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}


def normalize_letter(letter: str) -> str:
    return FINAL_MAP.get(letter, letter)


def sanitize_word(word: str) -> str:
    cleaned = []
    for char in word:
        normalized = normalize_letter(char)
        if "א" <= normalized <= "ת":
            cleaned.append(normalized)
    return "".join(cleaned)


def is_hebrew_letter(letter: str) -> bool:
    normalized = normalize_letter(letter)
    return "א" <= normalized <= "ת"


def word_length(word: str) -> int:
    return sum(1 for char in word if is_hebrew_letter(char))


def word_solved(word: str, guessed_letters: set[str]) -> bool:
    return all(not is_hebrew_letter(char) or normalize_letter(char) in guessed_letters for char in word)


def generate_room_id() -> str:
    while True:
        room_id = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        if room_id not in ROOMS:
            return room_id


def update_room_finish_state(room: dict[str, Any]) -> None:
    if room["finished"]:
        return
    if word_solved(room["word"], set(room["guessedLetters"])):
        room["finished"] = True
        room["won"] = True
        return
    if room["wrongGuesses"] >= MAX_WRONG:
        room["finished"] = True
        room["won"] = False
        return
    if room["deadline"] and time.time() >= room["deadline"]:
        room["finished"] = True
        room["won"] = False


class HangmanHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def room_payload(self, room: dict[str, Any]) -> dict[str, Any]:
        update_room_finish_state(room)
        remaining = 0
        if room["deadline"]:
            remaining = max(0, int(room["deadline"] - time.time()))
        guessed = set(room["guessedLetters"])
        return {
            "roomId": room["id"],
            "hostName": room["hostName"],
            "guestName": room["guestName"],
            "hostAvatar": room["hostAvatar"],
            "guestAvatar": room["guestAvatar"],
            "guestJoined": room["guestJoined"],
            "topic": room["topic"],
            "hint": room["hint"],
            "category": room["category"],
            "word": room["word"],
            "guessedLetters": room["guessedLetters"],
            "wrongGuesses": room["wrongGuesses"],
            "correctHits": sum(1 for char in room["word"] if is_hebrew_letter(char) and normalize_letter(char) in guessed),
            "finished": room["finished"],
            "won": room["won"],
            "remainingTime": remaining,
            "timeLimit": room["timeLimit"],
            "answer": room["word"] if room["finished"] else None,
        }

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]

        if parsed.path == "/api/health":
            self.end_json({"ok": True, "rooms": len(ROOMS)})
            return

        if len(parts) == 5 and parts[0] == "api" and parts[1] == "hangman" and parts[2] == "rooms" and parts[4] == "state":
            room = ROOMS.get(parts[3])
            if not room:
                self.end_json({"error": "room_not_found"}, HTTPStatus.NOT_FOUND)
                return
            self.end_json(self.room_payload(room))
            return

        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        data = self.read_json()

        if parts == ["api", "hangman", "rooms", "create"]:
            word = sanitize_word(str(data.get("word") or ""))
            if not word or word_length(word) < 2:
                self.end_json({"error": "invalid_word"}, HTTPStatus.BAD_REQUEST)
                return
            room_id = generate_room_id()
            time_limit = int(data.get("timeLimit") or 180)
            room = {
                "id": room_id,
                "hostName": str(data.get("hostName") or "שחקן 1"),
                "guestName": str(data.get("guestName") or "שחקן 2"),
                "hostAvatar": str(data.get("hostAvatar") or "😎"),
                "guestAvatar": str(data.get("guestAvatar") or "🦊"),
                "topic": str(data.get("topic") or "אונליין"),
                "hint": str(data.get("hint") or ""),
                "category": str(data.get("category") or "all"),
                "word": word,
                "guessedLetters": [],
                "wrongGuesses": 0,
                "finished": False,
                "won": False,
                "guestJoined": False,
                "timeLimit": time_limit,
                "deadline": time.time() + time_limit if time_limit > 0 else None,
                "createdAt": time.time(),
            }
            ROOMS[room_id] = room
            host = self.headers.get("Host") or "127.0.0.1:8001"
            self.end_json({
                "roomId": room_id,
                "joinUrl": f"http://{host}/index.html?hangRoom={room_id}"
            })
            return

        if len(parts) == 5 and parts[0] == "api" and parts[1] == "hangman" and parts[2] == "rooms" and parts[4] == "join":
            room = ROOMS.get(parts[3])
            if not room:
                self.end_json({"error": "room_not_found"}, HTTPStatus.NOT_FOUND)
                return
            room["guestJoined"] = True
            incoming_guest_name = data.get("playerName") or data.get("guestName")
            incoming_guest_avatar = data.get("avatar") or data.get("guestAvatar")
            if incoming_guest_name:
                room["guestName"] = str(incoming_guest_name)[:32]
            if incoming_guest_avatar:
                room["guestAvatar"] = str(incoming_guest_avatar)
            self.end_json({
                "roomId": room["id"],
                "hostName": room["hostName"],
                "guestName": room["guestName"],
                "hostAvatar": room["hostAvatar"],
                "guestAvatar": room["guestAvatar"],
                "timeLimit": room["timeLimit"],
            })
            return

        if len(parts) == 5 and parts[0] == "api" and parts[1] == "hangman" and parts[2] == "rooms" and parts[4] == "guess":
            room = ROOMS.get(parts[3])
            if not room:
                self.end_json({"error": "room_not_found"}, HTTPStatus.NOT_FOUND)
                return
            update_room_finish_state(room)
            if room["finished"]:
                self.end_json(self.room_payload(room))
                return
            letter = normalize_letter(str(data.get("letter") or "")[:1])
            if not is_hebrew_letter(letter):
                self.end_json({"error": "invalid_letter"}, HTTPStatus.BAD_REQUEST)
                return
            if letter not in room["guessedLetters"]:
                room["guessedLetters"].append(letter)
                if all(normalize_letter(char) != letter for char in room["word"] if is_hebrew_letter(char)):
                    room["wrongGuesses"] += 1
            update_room_finish_state(room)
            payload = self.room_payload(room)
            payload["hit"] = any(normalize_letter(char) == letter for char in room["word"] if is_hebrew_letter(char))
            self.end_json(payload)
            return

        self.end_json({"error": "unknown_endpoint"}, HTTPStatus.NOT_FOUND)


def main() -> None:
    port = int(os.environ.get("PORT", "8001"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HangmanHandler)
    print(f"Hangman server running on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
