# Normalization report: tiny-latex

- Normalization version: `it-v1`
- Lexicon SHA-256: `141d3a64c7b1549d6a7be3afb2ab8200fa96309b012c238f4fdb128e43193ef5`
- Blocks: 15
- Transformations: 7
- Warnings: 1

## Unresolved symbols and warnings

- `block-000009`: table-linearized: verify row and column reading order

## Applied lexicon entries

- None.

## Normalized blocks

### `block-000001`

**Display text**

Questa prefazione precede il primo capitolo.

**Spoken text**

Questa prefazione precede il primo capitolo.

**Transformations**

- None.

### `block-000002`

**Display text**

Fondamenti

**Spoken text**

Fondamenti

**Transformations**

- None.

### `block-000003`

**Display text**

Il primo paragrafo contiene una nota.

**Spoken text**

Il primo paragrafo contiene una nota.

**Transformations**

- None.

### `block-000004`

**Display text**

Nota esplicativa per il lettore.

**Spoken text**

Nota esplicativa per il lettore.

**Transformations**

- None.

### `block-000005`

**Display text**

Primo elemento.

**Spoken text**

Primo elemento.

**Transformations**

- None.

### `block-000006`

**Display text**

Secondo elemento.

**Spoken text**

Secondo elemento.

**Transformations**

- None.

### `block-000007`

**Display text**

Elemento annidato.

**Spoken text**

Elemento annidato.

**Transformations**

- None.

### `block-000008`

**Display text**

Una citazione conserva il proprio ruolo.

**Spoken text**

Una citazione conserva il proprio ruolo.

**Transformations**

- None.

### `block-000009`

**Display text**

Rendimenti annuali Anno Rendimento 2025 5%

**Spoken text**

Rendimenti annuali Anno Rendimento duemilaventicinque cinque per cento

**Transformations**

- `percentage`: `Rendimenti annuali Anno Rendimento 2025 5%` → `Rendimenti annuali Anno Rendimento 2025 cinque per cento`
- `integer`: `Rendimenti annuali Anno Rendimento 2025 cinque per cento` → `Rendimenti annuali Anno Rendimento duemilaventicinque cinque per cento`

### `block-000010`

**Display text**

r = \frac{utile}{capitale}

**Spoken text**

erre uguale a utile diviso capitale

**Transformations**

- `equation-fraction`: `r = \frac{utile}{capitale}` → `r = utile diviso capitale`
- `equation-operators`: `r = utile diviso capitale` → `r  uguale a  utile diviso capitale`
- `equation-identifiers`: `r  uguale a  utile diviso capitale` → `erre  uguale a  utile diviso capitale`
- `whitespace`: `erre  uguale a  utile diviso capitale` → `erre uguale a utile diviso capitale`

### `block-000011`

**Display text**

Andamento del capitale

**Spoken text**

Andamento del capitale

**Transformations**

- None.

### `block-000012`

**Display text**

Applicazioni

**Spoken text**

Applicazioni

**Transformations**

- None.

### `block-000013`

**Display text**

Il capitolo incluso verifica l’ordine dei file.

**Spoken text**

Il capitolo incluso verifica l'ordine dei file.

**Transformations**

- `unicode-cleanup`: `Il capitolo incluso verifica l’ordine dei file.` → `Il capitolo incluso verifica l'ordine dei file.`

### `block-000014`

**Display text**

Dettaglio

**Spoken text**

Dettaglio

**Transformations**

- None.

### `block-000015`

**Display text**

Un ultimo paragrafo chiude il piccolo libro.

**Spoken text**

Un ultimo paragrafo chiude il piccolo libro.

**Transformations**

- None.
