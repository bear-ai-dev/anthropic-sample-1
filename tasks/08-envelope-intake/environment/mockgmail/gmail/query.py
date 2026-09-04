from __future__ import annotations

import re
from datetime import datetime

from .models import Label
from .query_terms import Predicate, operator, text

_TOKEN = re.compile(r'(-?(?:[A-Za-z_]+:)?)"([^"]*)"?|([(){}])|(\S+)')
_TERM = re.compile(r'^(-?)(?:([A-Za-z_]+):)?(?:"([^"]*)"?|(.*))$', re.DOTALL)
_OPEN = {"(": ")", "{": "}"}


def _tokens(query: str) -> list[str]:
    found: list[str] = []
    for prefix, quoted, bracket, word in _TOKEN.findall(query):
        if bracket:
            found.append(bracket)
        elif word:
            found.extend(_split_bracketed(word))
        else:
            found.append(f'{prefix}"{quoted}"')
    return found


def _split_bracketed(word: str) -> list[str]:
    parts: list[str] = []
    rest = word
    prefix = ""
    if rest.startswith("-") and len(rest) > 1 and rest[1] in "({":
        prefix, rest = "-", rest[1:]
    while rest and rest[0] in "({":
        parts.append(prefix + rest[0])
        prefix, rest = "", rest[1:]
    tail: list[str] = []
    while rest and rest[-1] in ")}":
        tail.insert(0, rest[-1])
        rest = rest[:-1]
    if rest:
        parts.append(rest)
    return parts + tail


def _all(predicates: list[Predicate]) -> Predicate:
    return lambda message: all(predicate(message) for predicate in predicates)


def _any(predicates: list[Predicate]) -> Predicate:
    return lambda message: any(predicate(message) for predicate in predicates)


def _negate(predicate: Predicate) -> Predicate:
    return lambda message: not predicate(message)


class _Parser:
    def __init__(self, tokens: list[str], now: datetime, labels: tuple[Label, ...]) -> None:
        self.tokens = tokens
        self.index = 0
        self.now = now
        self.labels = labels

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self) -> str:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def sequence(self, closer: str | None, joined_by_or: bool) -> Predicate:
        units: list[Predicate] = []
        while (token := self._peek()) is not None and token != closer:
            if token in (")", "}"):
                self._take()
                continue
            if token == "OR":
                self._take()
                continue
            units.append(self._alternatives())
        if closer is not None and self._peek() == closer:
            self._take()
        return _any(units) if joined_by_or and units else _all(units)

    def _alternatives(self) -> Predicate:
        choices = [self._atom()]
        while self._peek() == "OR":
            self._take()
            if (token := self._peek()) is None or token in (")", "}", "OR"):
                break
            choices.append(self._atom())
        return _any(choices)

    def _atom(self) -> Predicate:
        token = self._take()
        negated = token.startswith("-") and len(token) > 1 and token[1] in "({"
        if negated:
            token = token[1:]
        if token in _OPEN:
            group = self.sequence(_OPEN[token], token == "{")
            return _negate(group) if negated else group
        return self._term(token)

    def _term(self, token: str) -> Predicate:
        found = _TERM.match(token)
        assert found is not None
        negated, name, quoted, bare = found.groups()
        value = quoted if quoted is not None else bare
        predicate = None if name is None else operator(name.lower(), value, self.now, self.labels)
        if predicate is None:
            raw = token[1:] if negated else token
            if not raw:
                return lambda message: True
            predicate = text(raw if name else value)
        return _negate(predicate) if negated else predicate


def matcher(query: str, now: datetime, labels: tuple[Label, ...]) -> Predicate:
    return _Parser(_tokens(query), now, labels).sequence(None, False)
