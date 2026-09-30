# Contributing

Thanks for helping make the Fly.io dashboard easier on the eyes.

## Reporting a page that looks wrong

[Open an issue](https://github.com/rojnwa/fly-io-dark-mode/issues/new/choose) with:

- the **page path** (e.g. `/apps/<app>/machines`)
- a **screenshot**
- your browser, Stylus version and theme version (shown in the Stylus manager)

A saved copy of the page makes fixes much faster. In your browser, use **Save page as → Webpage, Complete** and attach it as a zip. **Remove personal data first**: the saved HTML contains your email address, organization and app names, and GitHub repositories.

## Changing the theme

`fly-io-dark-mode.user.css` is **generated**. Please don't edit it by hand. All changes go into [`scripts/build.py`](scripts/build.py):

| You want to… | Edit |
| --- | --- |
| Change how colours map globally (surfaces, text, borders, tints) | `t_bg`, `t_text`, `t_border`, `t_shadow` and the curves above them |
| Adjust a Fly component (buttons, badges, cards, inputs, tooltips…) | `PATCH_SRC`, keyed by the component's original selector |
| Style something the site never styles | `ADDITIONS` |
| Change which URLs the style applies to | `URL_MATCH` |

Then rebuild:

```sh
python scripts/build.py
```

To see your changes, open the style in the Stylus editor, paste in the rebuilt file and save. Or install the local file once (allow the extension access to file URLs) and turn on Stylus's **Live reload**.

## Pull requests

- Commit `scripts/build.py` and the regenerated `fly-io-dark-mode.user.css` together.
- For visible changes, include before/after screenshots. Use example data, not your real org or app names.
- Bump `VERSION` in `scripts/build.py` and add an entry to [CHANGELOG.md](CHANGELOG.md). Stylus only offers an update when the version number goes up.
