# Extraction report: tiny-pdf

- Source format: `pdf`
- Source SHA-256: `2508a140b135ea3b8bbdd5b7971fa998ad028fa793defc6816187e461cffa2ed`
- Chapters: 2
- Blocks: 10
- Warnings: 2
- Exclusions: 2

## Warnings

- pdf-header-footer-excluded: verify that no narratable content occupied those regions
- `block-000007`: table-linearized: verify row and column reading order

## Exclusions

- `pdf-header-footer` at `source/book.pdf`, page 1: Page header and footer regions excluded throughout the PDF by policy
- `non-narratable-image` at `source/book.pdf`, page 2: PDF image region without separate narratable text excluded

## Extracted chapters

### 1. 1 Fondamenti PDF

#### `block-000001` — heading — `source/book.pdf`, page 1

1 Fondamenti PDF

#### `block-000002` — paragraph — `source/book.pdf`, page 1

Il primo paragrafo occupa la colonna sinistra e conserva l'ordine di lettura.

#### `block-000003` — paragraph — `source/book.pdf`, page 1

La seconda colonna segue la prima senza mescolare le frasi.

#### `block-000004` — list_item — `source/book.pdf`, page 1

Primo elemento

#### `block-000005` — list_item — `source/book.pdf`, page 1

Secondo elemento

#### `block-000006` — paragraph — `source/book.pdf`, page 1

Una citazione PDF mantiene una posizione riconoscibile.

#### `block-000007` — table — `source/book.pdf`, page 1

Anno Rendimento 2024 4 per cento 2025 5 per cento

### 2. 2 Applicazioni PDF

#### `block-000008` — heading — `source/book.pdf`, page 2

2 Applicazioni PDF

#### `block-000009` — paragraph — `source/book.pdf`, page 2

Il secondo capitolo verifica il cambio pagina e le sorgenti numerate.

#### `block-000010` — paragraph — `source/book.pdf`, page 2

Figura 1: andamento del capitale.
