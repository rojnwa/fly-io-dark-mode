# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.2.1] - 2026-09-30

### Fixed
- Text in the fly.toml viewer (app → fly.toml → Full config) was black on the dark background. The page hard-codes an inline `color: #000000 !important`, so the theme now paints over it with `-webkit-text-fill-color`.

## [1.2.0] - 2026-09-30

### Added
- `scripts/build.py`: the generator that builds the theme from Fly's live stylesheet (standard library only).
- `@homepageURL`, `@supportURL` and `@updateURL`, so Stylus can update the style automatically.

### Changed
- Renamed to **Fly.io Dark Mode**, file `fly-io-dark-mode.user.css`.
- Default buttons, disabled buttons and modals now use the same raised colours as the rest of the palette.

### Fixed
- The Fly logo no longer looks inverted. Its balloon and mountain linework is now dark, like the logo on docs.fly.io in dark mode.

## [1.1.0] - 2026-09-30

### Fixed
- The page turned white about a second after loading. The dashboard puts a pastel background photo on `<body>`, which is now replaced by dark glows in the same spots.
- A solid navy block appeared behind the sidebar on wide screens. Every colour rule is now copied in the original cascade order, so rules like `lg:bg-transparent` win again.
- Status dots (e.g. the green "running" dot) were dimmed. Vivid signal colours now keep their original colour.
- Cards and small pills stood out too little from the page.

## [1.0.0] - 2026-09-30

### Added
- First release: dark theme for the Fly.io dashboard and sign-in page.

[1.2.1]: https://github.com/rojnwa/fly-io-dark-mode/releases/tag/v1.2.1
[1.2.0]: https://github.com/rojnwa/fly-io-dark-mode/releases/tag/v1.2.0
[1.1.0]: https://github.com/rojnwa/fly-io-dark-mode/releases/tag/v1.1.0
[1.0.0]: https://github.com/rojnwa/fly-io-dark-mode/releases/tag/v1.0.0
