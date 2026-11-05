# Rights, claims and data

Say in the final report what you verified and what the user still has to confirm. Never write that something is free to use, licensed or accurate unless its source says so.

## What the film claims

- **Real features only**, shown as they work. Read the code path of every feature you show; try it in the Simulator when you can.
- **Opt-in features** (notifications, AI, bank sync, location) appear as the user turning them on or using them, never as the default state.
- **Where processing happens.** If recognition runs on a server or a third-party API, don't show or say "on device", "offline" or "private", and the other way round.
- **No numbers you can't source**: accuracy, speed, savings, user counts, ratings, awards, "#1".
- **Prices and plans** only as the app sells them today; leave them out if unsure.
- **App Store app previews** may only use screen captures of the app itself, with narration and text overlays allowed on top (App Review Guideline 2.3.4), and should not show prices (2.3.7). A rebuilt HTML film is for the website, social posts, press and launch pages. If the user asks for an App Store preview, say so and offer this film for those channels and/or a preview recorded from the app:
  - record the Simulator while playing through the beat map with fictional data: `xcrun simctl io booted recordVideo --codec=h264 --force take.mov` (Ctrl-C stops it);
  - cut the music for 30 fps: `music_edit.py … --fps 30`; edit the takes to it with ffmpeg, scaled to the preview size;
  - deliver what App Store Connect accepts: 15–30 s, at most 30 fps, 886 × 1920 portrait for 6.1–6.9″ iPhones, H.264 with stereo 256 kbps AAC; the poster frame defaults to 5 s. Previews autoplay muted, so captions must carry the story.

## Data on screen

All names, merchants, amounts, balances, dates, cards, accounts and people are fictional and plausible. Card numbers show only fictional last digits. No real customer data, even blurred. Use the currency and locale the audience expects (ask if unclear).

## Music

Record in `audio/SOURCE.md`: title, artist, source URL, licence name and link, the date it was obtained, the bars used, and any attribution the licence requires. Library licences differ on commercial use, ads, paid promotion, standalone redistribution and YouTube Content ID; quote the licence's own words for the use the user plans. If the user supplies a track, ask whether they hold the rights for this use.

A track made with ACE-Step 1.5: its code and weights are MIT-licensed, and its model card allows commercial use of what it makes; record the model, the caption, the seed and the date in place of an artist and a licence. Whether music made by AI can be protected by copyright differs by country, and some platforms ask for AI-made audio to be labelled. Tell the user both. Sounds for the actions come from `sfx.py`, synthesized for the film: original, nothing to credit.

## Brands and marks

- **Merchant logos** (in lists of payments, for example) are trademarks of their owners. Use them only with the user's agreement, at list-item size, never implying a partnership. Neutral lettered avatars are the safe default.
- **The iPhone** in the film is a drawn generic frame. Follow Apple's marketing guidelines when the name "iPhone" or Apple badges appear; use Apple's official badge artwork, never a redrawn one.
- **SF Symbols and SF Pro** are licensed for mock-ups of software for Apple platforms; use them as part of the app's UI, never as a logo or outside the phone. Prefer the app's own font when it has one.

## Voices

- Chatterbox (Resemble AI, MIT) output carries Resemble's inaudible Perth watermark. Clone only a voice the user has the rights to: theirs, or one with written consent for this use. Never imitate a real person without consent.
- Kokoro-82M and its preset voices are released under Apache-2.0 (its model card); no cloning, so no one's voice is imitated.
- The macOS `say` voices are for personal, non-commercial use under the macOS licence: use them for drafts and timing only.
- Say which voice and model made the final mix.

## Files

Never overwrite the user's source assets; everything derived goes in the film folder. Keep `out/` (renders) and `audio/source/` (downloaded originals) out of git.
