# Repository Guidelines

## Formål og arkitektur

Agentbox kjører kodeagenter i en egen rootless Docker-instans som Linux-brukeren
`agentbox`, med hjem `/var/lib/agentbox`. Hvert miljø har en agentcontainer på
et lukket nettverk og en Squid-proxy med eksplisitt tillatte domene/port-par.
Det medfølgende utviklingsimaget inneholder Codex; imagevalg er adskilt fra isoleringen.
Eksisterende prosjektmapper monteres direkte med ACL-basert tilgang.
Worktree-støtte er utsatt.

## Prosjektstruktur

- `src/agentbox/`: Python-CLI, kontrollhjelper, konfigurasjon, ACL, nettverk og tilstand.
- `src/agentbox/completions/`: Bash-completion, installert av vertsinstalleren.
- `images/dev/` og `images/smoke/`: Codex-image og separat testimage.
- `proxy/`: Squid-image; policy genereres av `src/agentbox/policy.py`.
- `environments/`: miljøkonfigurasjoner uten hemmeligheter.
- `scripts/install.sh` og `scripts/uninstall.sh`: administratoroppsett og avinstallasjon.
- `scripts/lab/`: disponibel KVM-lab.
- `tests/unit/` og `tests/integration/`: pytest-tester.
- `security/vendor/`: revisjonslåst Moby-seccomp-grunnlag.
- `docs/`: produktspesifikasjon, arkitektur, bruk, installasjon og testbevis.
- `docs/history/`: arkivert implementeringsplan fra MVP-arbeidet.

## Bygging, testing og utvikling

Bruk Python 3.12 eller nyere og avhengighetene i `uv.lock`:

```sh
uv sync --extra dev --locked
uv run --locked pytest -q
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
bash -n scripts/*.sh scripts/lab/*.sh images/dev/codex src/agentbox/completions/agentbox.bash
```

`pytest` kjører enhetstestene som standard. Integrasjonstesten krever installert
kontrollverktøy, `AGENTBOX_LAB=1` og verten `agentbox-lab`; følg
[laboppskriften](docs/test-results.md). Kjør sikkerhetsprøver i disponibel VM. Avinstallasjonsprøven krever separat
`AGENTBOX_UNINSTALL_LAB=1` og skal kjøres sist; den sletter labinstallasjonen.
På installert system bygger `agentbox build-images` utviklingsimage og proxy.

## Kodestil og dokumentasjon

Bruk fire mellomrom i Python, Ruff med 100 tegns linjelengde og to mellomrom
i YAML. Bashskript skal ha eksplisitt feilhåndtering. Bruk `test_*.py` og
`test_*` for tester; ingen dekningsprosent er konfigurert.
Oppdater relevant dokumentasjon ved endret oppførsel. C4-kilden ligger i
`docs/architecture-c4.md`; regenerer SVG og PNG med
`python3 scripts/render-diagrams.py` og samme kommando med `--format png`.

## Sikkerhet og verifikasjon

Behold fast Docker-socket, identitetskontroll og avgrenset sudo-hjelper.
Ikke innfør privilegerte containere, vertsnettverk eller Docker-socket i agenten.
Test tillatt proxytrafikk, avvisning, direkte tilgang og ACL-konsekvenser ved
relevante endringer. Skill observerte labresultater fra utestede garantier.
Agentbox 1.0 er verifisert gjennom labprøver og manuell Codex-bruk på verten.
Ikke sjekk inn hemmeligheter, `.lab/` eller private logger.

## Commits og pull requests

Gjør videre arbeid på egne grener fra `main`; ikke commit direkte til `main`.
Lever endringer som pull requests og bruk squash merge til `main`.
Slett arbeidsgrenen både lokalt og på GitHub etter merge.

Oppdater relevant dokumentasjon i samme arbeidsgren før merge. Kode, bruk,
konfigurasjon, arkitektur og teststatus skal stemme overens ved merge til `main`.
Ved endrede diagrammer skal både kilde og genererte bilder følge med.
Dokumentasjonsoppdateringen er en del av leveransen og skal ikke utsettes
til etter merge; hovedgrenen skal inneholde et komplett produkt.

Bruk korte, handlingsorienterte meldinger, som `Build initial rootless agent
isolation MVP`. Squash-committen skal beskrive de faktiske endringene kort og
konkret, uten prosa. Vi vedlikeholder foreløpig ingen egen endringslogg.
Beskriv formål, endret oppførsel og
utførte tester i pull requests. Forklar konsekvenser for isolering, proxyregler,
monteringer og lagring når disse berøres.
