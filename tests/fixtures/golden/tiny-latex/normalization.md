# Normalization report: tiny-latex

- Normalization version: `it-v1`
- Lexicon SHA-256: `74f84406884436bd6cdd781a24a7dd1c1e5ef4c944cc1ba5913088d94b08ec36`
- Blocks: 15
- Changed blocks: 2
- Transformations: 6
- Lexicon applications: 0
- Warnings: 1
- Unchanged, warning-free blocks omitted: 13

## Warnings by reason

- `table-linearized: verify row and column reading order`: 1 occurrence

## Transformations by rule

- `equation-fraction`: 1 application
- `equation-identifiers`: 1 application
- `equation-operators`: 1 application
- `integer`: 1 application
- `percentage`: 1 application
- `whitespace`: 1 application

## Blocks requiring review

### `block-000009`

- Warnings: `table-linearized: verify row and column reading order`

**Spoken text**

Rendimenti annuali Anno Rendimento duemilaventicinque cinque per cento

**Changes**

- `percentage`: `5%` → `cinque per cento`
- `integer`: `2025` → `duemilaventicinque`

### `block-000010`

**Spoken text**

erre uguale a utile diviso capitale

**Changes**

- `equation-fraction`: removed `\frac{`; `}{` → `diviso`; removed `}`
- `equation-operators`: `=` → `uguale a`
- `equation-identifiers`: `r` → `erre`
- `whitespace`: whitespace normalized
