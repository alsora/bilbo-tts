# Normalization report: tiny-latex

- Normalization version: `it-v1`
- Lexicon SHA-256: `141d3a64c7b1549d6a7be3afb2ab8200fa96309b012c238f4fdb128e43193ef5`
- Blocks: 15
- Changed blocks: 3
- Transformations: 7
- Lexicon applications: 0
- Warnings: 1
- Unchanged, warning-free blocks omitted: 12

## Warnings by reason

- `table-linearized: verify row and column reading order`: 1 occurrence

## Transformations by rule

- `equation-fraction`: 1 application
- `equation-identifiers`: 1 application
- `equation-operators`: 1 application
- `integer`: 1 application
- `percentage`: 1 application
- `unicode-cleanup`: 1 application
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

### `block-000013`

**Spoken text**

Il capitolo incluso verifica l'ordine dei file.

**Changes**

- `unicode-cleanup`: `l’ordine` → `l'ordine`
