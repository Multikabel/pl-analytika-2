# v1.2 – Celkové trhy zápasu

Přidány:
- Fauly celkem
- Rohy celkem
- Karty celkem

Predikce celku = součet očekávaných počtů obou týmů.

Pravděpodobnost Over není součtem týmových pravděpodobností.
Počítá se z distribuce součtu obou týmových count modelů. Pro Poisson je
součet Poisson; pro negative-binomial model používáme momentově přizpůsobenou
NB distribuci se součtem týmových variancí.

Celkové trhy používají dynamické půlbodové hranice kolem predikovaného
match totalu a procházejí stejným fair-odds filtrem.

Stejně jako týmové tipy:
1. ručně zaškrtnout,
2. zadat skutečný bookmaker kurz,
3. uložit,
4. po zápase automaticky WIN/LOSS,
5. započítat kurz, profit a ROI.

Vyhodnocení celkového trhu sčítá skutečnou hodnotu domácího a hostujícího týmu.
