# Lager Documentation

Documentation for the Lager platform, built with [Mintlify](https://mintlify.com/).

## Doc Structure

The documentation is organized into 5 tabs (defined in `docs.json`):

1. **Overview** - Getting started guides, architecture, troubleshooting, glossary
2. **CLI Reference** - All `lager` CLI commands (power, measurement, I/O, development, utilities)
3. **Python API** - On-box Python API reference (`from lager import Net, NetType`)
4. **Supported Instruments** - Hardware compatibility list
5. **Release Notes** - Version history

Source files live in `source/` as `.mdx` (Markdown + JSX) files.

## Development

Install the [Mintlify CLI](https://www.npmjs.com/package/mintlify):

```bash
npm i -g mintlify
```

Preview docs locally (run from the `docs/` directory where `docs.json` lives):

```bash
cd docs
mintlify dev
```

## Troubleshooting

- **Mintlify dev isn't running** - Run `mintlify install` to re-install dependencies.
- **Page loads as a 404** - Make sure you are running in the `docs/` folder (where `docs.json` is).
