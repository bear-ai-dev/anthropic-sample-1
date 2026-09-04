from mockgmail.gmail.models import Message
from mockgmail.gmail.state import GmailState


def message_by_key(state: GmailState, key: str) -> Message:
    return next(message for message in state.messages if message.key == key)
