# Statistiky NHL

Přehledné statistiky hráčů, brankářů a týmů NHL v češtině: základní čísla, pokročilé statistiky (xG, Corsi, GSAx), mapy střel, formace a podrobnosti každého zápasu.

Stránka se aktualizuje sama každý den ráno a v poledne (GitHub Actions → `build.py`) a je zveřejněná přes GitHub Pages.

## Jak to funguje

- `page.html` – vzhled a logika stránky
- `build.py` – stáhne data a uloží je do složky `site/` (tu GitHub Pages zveřejňuje)
- `cache/` – už stažené zápasy, aby se nemusely stahovat znovu
- `.github/workflows/update.yml` – plán automatické aktualizace

Ruční spuštění: záložka **Actions** → **Aktualizace statistik** → **Run workflow**.

## Zdroje dat

- [NHL.com](https://www.nhl.com) – oficiální statistiky, tabulka, zápisy a události zápasů
- [MoneyPuck.com](https://moneypuck.com) – xG, Corsi, GSAx, formace a data jednotlivých střel (zdarma pro nekomerční použití s uvedením zdroje)

Projekt je nekomerční.
