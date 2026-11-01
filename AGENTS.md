# Repository Guidelines

## Formål og arkitektur

Agentbox kjører kodeagenter i en egen rootless Docker-instans som Linux-brukeren
`agentbox`, med hjem `/var/lib/agentbox`. Hvert miljø har en agentcontainer på
et lukket nettverk og en Go-proxy med eksplisitt tillatte domene/port-par.
Det medfølgende utviklingsimaget inneholder Codex; imagevalg er adskilt fra isoleringen.
Eksisterende prosjektmapper monteres direkte med ACL-basert tilgang.
Worktree-støtte er utsatt.

Debian er minste målplattform. Ubuntu kan brukes i laben, med separat
Debian-utprøving. Konkret minste distroversjon skal dokumenteres; proxyens
pakkeflavour eller upstream-build kan endres når kravene tilsier det.

## Prosjektstruktur

- `src/agentbox/`: Python-CLI, kontrollhjelper, konfigurasjon, ACL, nettverk og tilstand.
- `src/agentbox/completions/`: Bash-completion, installert av vertsinstalleren.
- `images/dev/` og `images/smoke/`: Codex-image og separat testimage.
- `proxy/`: Go-proxy, tester og flertrinns imagebygg; JSON-policy genereres av `src/agentbox/policy.py`.
- `environments/`: miljøkonfigurasjoner uten hemmeligheter.
- `scripts/install.sh` og `scripts/uninstall.sh`: administratoroppsett og avinstallasjon.
- `scripts/lab/`: disponibel KVM-lab.
- `tests/unit/` og `tests/integration/`: pytest-tester.
- `security/vendor/`: revisjonslåst Moby-seccomp-grunnlag.
- `docs/`: produktspesifikasjon, arkitektur, bruk, installasjon og testbevis.

## Bygging, testing og utvikling

Bruk Python 3.12 eller nyere og avhengighetene i `uv.lock`:

```sh
uv sync --extra dev --locked
uv run --locked pytest -q
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
bash -n scripts/*.sh scripts/lab/*.sh images/dev/codex src/agentbox/completions/agentbox.bash
(cd proxy && go test -race ./... && go vet ./...)
(cd proxy && GOTOOLCHAIN=go1.27.3 go run golang.org/x/vuln/cmd/govulncheck@v1.9.0 ./...)
test -z "$(gofmt -l proxy/*.go)"
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
Ekte tokens leses fra operatørens eksplisitte miljøvariabler og gis bare til proxyens miljø.
Reglenes `env` støtter `klient=kilde`; kortform bruker samme navn. Ny
opprettelse med tom/manglende kilde gir tom klientvariabel. Ellers får agenten
genererte plassholdere; bare eksakt treff i
autorisert header/destinasjon byttes til ekte token.
Ingen tokenverdier i konfigurasjon, argumenter, tilstand eller logger. Docker-metadata
kan inneholde token; fullt utbrudd til tjenestebrukeren er utenfor denne beskyttelsen.
Kjør labprøver sekvensielt siden de endrer felles vertsnettverk og innstillinger.
Ikke sjekk inn hemmeligheter, `.lab/` eller private logger.

## Arbeidsprosess

Arbeid i rekkefølgen spec → research → plan → implementasjon og verifikasjon.
Under arbeid lagres fasene midlertidig under `docs/features/<tema>/`:

1. `spec.md`: brukerens mål, omfang, krav og målbare akseptansekriterier.
2. `research.md`: kilder, tekniske prøver, alternativer og avklaringer mot kravene.
3. `plan.md`: gjennomføringssteg som dekker spec-en med støtte i researchen.
4. Verifikasjonsfiler: kommandoer, testmiljø, forventning og observerte resultater.

Oppdater fasestatus, beslutninger og åpne spørsmål i filene underveis.
Samtalekonteksten skal ikke være eneste sted viktig informasjon finnes.
Skill forslag fra vedtatte valg; research skal ikke omtales som gjennomført
før funn og grunnlag er lagret.

Før levering samles gjeldende krav i produktspesifikasjonen, begrunnelser i
arkitekturvalg og verifikasjon i teststatus. Behold kjørbare tester og viktige
sikkerhetsbegrensninger. Slett ferdige arbeidsplaner, forskningsprototyper,
rålogger, utdaterte rapporter og disponible labdata. Ikke behold arkiver av
mellomsteg bare som arbeidshistorikk; ferdig dokumentasjon skal beskrive
programmet og det fremtidige utviklere trenger.

La en ny, uavhengig subagent gjennomgå spec og plan. Lagre funn og hvordan
de håndteres før neste fase. Velg den enkleste løsningen som oppfyller kravene;
begrunn nye komponenter og mekanismer med konkrete behov. Unngå generell
funksjonalitet som ikke trengs for leveransen.

Oversikt er en forutsetning for sikkerhet. Når ansvar, dataflyt eller regler
blir vanskelige å følge, skal vi forenkle og gjøre dem forståelige før vi
bygger videre. Flere tester erstatter ikke en forståelig sikkerhetsmodell.

Research kartlegger muligheter og begrensninger; den skal ikke låse utfallet.
Tekniske prøver skal beskrive hva de faktisk viser, på hvilken build/plattform,
og hvilke kandidater eller spørsmål som fortsatt er åpne.

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
