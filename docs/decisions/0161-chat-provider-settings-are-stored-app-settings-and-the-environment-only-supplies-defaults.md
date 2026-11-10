# 0161. Chat settings are stored app settings; the environment only supplies defaults

Status: accepted

Context: The summary settings (decisions 0110-0116) already keep a user's choice in the app-setting store so the UI can change it later. Chat has the same shape: enabled, provider kind, address, model.
Decision: `services/chat_settings.py` (`ChatSettings`) reads and writes `chat.enabled`, `chat.kind`, `chat.base_url`, `chat.model`, `chat.include_history` and `chat.include_notes` in the app-setting store; every call runs off the event loop. A stored kind wins as a block: if the user saved a kind, the address and model come from the store (or are empty), never from the environment, so a default address cannot be mixed with a stored kind. With nothing stored, `CC_CHAT_ENABLED`, `CC_CHAT_PROVIDER`, `CC_CHAT_BASE_URL` and `CC_CHAT_MODEL` supply the values; chat is OFF by default (rule 6). `normalise_provider` validates a choice (`InvalidChatSettingError` says what is wrong, never echoes the address). The keys are permanent identifiers.
Alternative: Environment only (the UI could not change it); store the address with the key in the keychain (the address is not secret, and a settings page needs to show it).
Reason: One place says what chat will do, and the environment cannot silently override a choice the user made in the UI.
Where: `src/command_center/services/chat_settings.py`, `config.py`, `app.py`; `tests/test_chat_settings.py`.
Revisit when: The settings UI lands; it calls the same setters.
