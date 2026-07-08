# fixtures/

This directory is for **local, uncommitted** audio files used for manual
testing of the real analysis pipeline once it exists. It is not used by
the automated test suite — those tests use `tests/fixtures/*.json`
(pre-computed analysis data, no audio).

## Rules

- **Never commit audio files here.** This directory should stay empty in
  git except for this README. Anything you drop in here for local testing
  is your responsibility, license-wise.
- Use audio you own the rights to, or that's explicitly licensed for this
  kind of use (e.g. royalty-free sample packs, your own recordings,
  Creative-Commons-licensed tracks with attribution kept alongside the
  file). Do not add commercially released songs.
- Suggested local layout (all gitignored):
  ```
  fixtures/
    local/
      song_a.mp3
      song_b.mp3
  ```
- If you need shareable, reproducible test data, generate a short
  synthetic WAV (e.g. a sine sweep or click track) rather than using a
  real song. The repo's `.gitignore` blocks common audio extensions
  repo-wide as a safety net, so an intentional synthetic fixture needs an
  explicit `git add -f path/to/file.wav`.
