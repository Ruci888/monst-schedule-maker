v1.1.0-beta.9.24e — Anchor-to-text-fragment fix

Based on v1.1.0-beta.9.24d.

Changes:
- app.py: Existing legacy URL anchors (#5, #10, etc.) are replaced with
  name-based #:~:text= fragments.
- Existing explicit #:~:text= fragments remain unchanged.
- Plain URLs continue to generate fragments from event name.
- event_image_generator.py is included unchanged from 9.24d for consistency.

Upload both app.py and event_image_generator.py to repository root.
Commit: v1.1.0-beta.9.24e Fix anchor-based event news links
