# Consented voices for voice cloning (IndicF5)

The system can speak in a real person's voice only with that person's written consent.
Create `data/voices/<voice_id>/` containing:

- `reference.wav`: 5–15 seconds of the speaker reading `reference_text`, recorded in a quiet room.
- `consent.yaml`:

```yaml
speaker_name: <full name>
signed_on: 2026-10-20
permitted_use: Generated explanations in the GR assistant pilot and its demo videos
withdrawal_contact: <email or phone>
reference_audio: reference.wav
reference_text: <exact words spoken in reference.wav>
```

Without a complete `consent.yaml`, `IndicF5Clone` refuses to load. Audio made with a cloned voice is still
synthetic speech and is labelled as AI-generated wherever it is played. Recordings and consent forms contain
personal data, so `.gitignore` keeps `*.wav` out of the repository. Store signed consent forms in the
approved document system.
