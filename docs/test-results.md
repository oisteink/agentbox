# Teststatus for Agentbox

Teststrategi og navngitte kravbevis står i [testoversikten](testing.md).
Sist verifisert 2. november 2026 på `feature/local-images`.
Resultatene
nedenfor gjelder observerte prøver, ikke en garanti for alle feiltilstander.

## Lokale imageoppskrifter, 2. november 2026

På `feature/local-images` bestod 178 Python-enhetstester med Python 3.13 og
pytest 9.0.3. Ruff lint/format, Bash-syntaks og `git diff --check` bestod.
`scripts/check.sh` bestod også Go race/vet, govulncheck og gofmt; etter
rettelsen av byggkonteksten ble Python-, Ruff- og Bash-kontrollene kjørt igjen.
Go-koden er uendret. Image- og proxyhjelpen viser den nye kommandostrukturen.
C1/C2 ble rendret til SVG og PNG og bildene kontrollert visuelt.
Wheel-bygg bestod og inkluderer begge Dockerfile-malene og Codex-launcheren.

Nye lokale prøver dekker oppskrift uten overskriving, malinnhold, binær
tar-overføring over 1 MiB etter begrenset JSON-header, lenker uten
dereferering, avslag på spesialfiler og usikker utpakking, eksakt image-ID,
stoppede containere, labeltilhørighet og profilfeil. Docker-grensen erstattes
i disse prøvene; de viser ikke faktisk installert Docker-oppførsel.

Uavhengig spec-/plangjennomgang presiserte binær protokoll, eksisterende
imagekontrakt og eksakt ID-sjekk. Kodegjennomgangen fant at BuildKit hopper
over .dockerignore ved upload av tar-kontekst. Byggingen bruker derfor en
privat utpakket katalog med datafilter og Dockers vanlige katalogbygg.
Laboppsettet kopierer også aktuell Codex-mal før bygg for å unngå gamle
lokale oppskrifter i gjentatte prøver.

`scripts/lab/check.sh --uninstall` bestod i en ny disponibel KVM-VM:
Ubuntu 24.04.5 amd64, kernel 6.8.0-147-generic, Python 3.12.3, pytest 9.0.3
og rootless Docker 29.9.2. Alle 13 livssyklusscenarioer bestod på 95,21
sekunder, de 24 proxykontrollene bestod uten cleanupfeil, og avinstallasjon
bestod på 6,71 sekunder. Ingen skips eller testfeil i sluttkjøringen.
Installert kilde ble sammenlignet med prosjektkilden før prøvene.

`test_local_image_build_context_and_use_guard` bekreftet COPY/.dockerignore,
bygg/fjerning under kjørende og stoppet bruk, proxyens brukssperre og
ombygging etter remove med bevart prosjektfil. Eksisterende prøver bekreftet
nettverksavslag, tillatt proxytrafikk, ACL-oppførsel og bevart containerlag ved
stopp/start. Prøvene bruker syntetiske tokens, uten ekte nøkler eller modellkall.
`test_edit_image_uses_operator_editor_and_returns_status` bekreftet lokal
editorstart som utvikleren, siterte argumenter, absolutt Dockerfile og riktig
arbeidskatalog, arvet inn-/utdata, filendring og editorens exitkode. Lokale
prøver dekker VISUAL/EDITOR/editor og at ingen kontroll-RPC utføres.
Spec, plan og kode for edit ble gjennomgått uavhengig uten nye feilfunn.
VM-en ble stoppet, og disponible labdata og rålogger ble fjernet etter prøvene.

## Lokalt navnebytte til abx, 2. november 2026

På utviklingsverten bestod `uv run --locked pytest -q` med 147 tester,
`ruff check src tests scripts`, `ruff format --check src tests scripts` og
Bash-syntakskontroll av hvert skallskript og `completions/abx.bash`.
`uv run --locked abx --help` viste `usage: abx`; completion-testene kontrollerte
registrering for `abx` og dynamiske oppslag via samme navn.
Vertsinstallasjon, oppgradering og avinstallasjon med nytt navn er ikke prøvd i lab.
Brukeren har meldt om lokal installasjon og en lett manuell prøve; omfanget er ikke spesifisert.
Go-proxyen er uendret; tidligere labresultater nedenfor gjelder før navnebyttet.

## Miljø og resultater

VM: Ubuntu 24.04.5, amd64, kernel 6.8.0-147-generic, rootless Docker 29.9.2
og systemd/cgroup v2. Proxyimaget bruker Debian 13, Go 1.27.3 og goproxy v1.9.2.
Codex CLI 0.166.0 er prøvd. Ny Go-proxy er ikke prøvd på Debian-verten;
minste Debian-versjon er ikke fastsatt.

| Kontroll | Resultat | Sist kjørt |
| --- | --- | --- |
| Python-enhetstester, pytest 9.0.3 | 147 bestått | 2. november |
| Ruff lint/format, Bash-syntaks og gofmt | Bestått | 2. november |
| Go race-deteksjon og vet | Bestått, HTTP/1 og HTTP/2 | 2. november |
| govulncheck v1.9.0 med Go 1.27.3 | Ingen sårbarheter som kan nås | 2. november |
| Installer og bygg produksjonsimages i VM | Bestått; installerte filer sammenlignet med kilde | 2. november |
| Installert proxyakseptanse | 24 kontroller, syntetiske nøkler, ingen cleanupfeil | 2. november |
| Installert CLI-livssyklus | 11 selvstendige scenarier bestått, 76,44 sekunder, ingen skips | 2. november |
| Codex med ChatGPT device-login og Context7 | Én read-only modellkjøring fullførte resolve-library-id | 31. oktober |
| Avinstallasjon i disponibel VM | 1 bestått, 6,50 sekunder; øvrig rootful Docker bevart | 2. november |

Lokale kontroller ble kjørt med `scripts/check.sh`. Laben ble opprettet på nytt
og fullført med `scripts/lab/check.sh --uninstall`, Python 3.12.3 og pytest 9.0.3
fra låsefilen. Ingen ekte nøkler eller modellkall ble brukt i denne runden.
Installasjon og Codex-bruk fra 1.0/1.0.1 er tidligere prøvd manuelt på
utviklerens Debian-vert.

## Regresjonsbevis og prøvegrunnlag

Oppstart og avinstallasjon er prøvd med en privat målkatalog bak et nestet
bind-mount. Begge skannere hopper over mountpunktet før åpning. De lokale
regresjonsprøvene feilet med PermissionError på den tidligere rekkefølgen og
består etter rettingen. Den installerte prøven kontrollerer også uendret
eierskap og identitet på en beskyttet fil utenfor prosjektet.

Midlertidige feilvarianter ble installert i VM-en: tvungen exitkode 0 ble
oppdaget av exec-testen, og sletting av hjemmemarkøren ved gjenopptak ble
oppdaget av bevaringstesten. Normal kode besto begge igjen etter gjeninstallasjon.
Feil etter faktisk start ble ryddet opp med tomt miljøregister etterpå;
rapportert cleanupfeil ga teardown-feil. Feil vert med labflagg ble avvist før
oppsett. Vanlig kjøring av integrasjonstestene uten flagg hoppet over 12 tester;
dette er ingen installert akseptanseprøve.

Installerte kildefiler, testpakke og images ble registrert av labinngangen.
Hashene følger beregningen i `scripts/lab/check.sh`:

```text
installert kilde: 0fc50dd3ee759008625fbf3b116efe8a9c414b5e5a85f26cfe0377b55864cbf9
testpakke:       a059e89528132247bf5e5fddcb58416122ae631635f1a5add0ab32edbf392762
dev:local:       9ec81e73872b0bc9cbab61e9cc4fcdff657eaf7a99e8e152d1b904e52b8065c7
dev:lab:         a77871154b8efd4ebf7dfca6616b912a2afbfa283ad85f48dc839e1dfeaa1e56
proxy:local:     ede7f132e13e084843045748199c31d331c6e8f624265134e70a0e778938f1b7
proxy:lab:       dba9b9e1c78c2190807f86f48575538133f38fd1ea36190f202f3534a436b472
```

Images har prefikset `agentbox-`, og image-ID-ene har prefikset `sha256:`.
Rålogger, feilvarianter og disponibel VM beholdes ikke som arbeidshistorikk.

## Hva prøvene dekker

`tests/unit/` og Go-testene i `proxy/` dekker parser, RPC, aliasretning,
indeksrekkefølge, delt kilde, aktive/tomme regler, headernormalisering,
TLS-binding og negative feilbaner. Destinasjoner med bare tomme referanser
bruker fortsatt miljøets CA; en rå tunnel ville feile den positive TLS-prøven.

`scripts/lab/credential_proxy.py` kjører mot installert CLI og faktiske
rootless-containere. En kontrollert TLS-tjeneste i egen nettverksnamespace
observerer requestene. En fungerende kontrollklient bekrefter tjenesten før
avslag godtas. Bare syntetiske nøkler brukes:

- Riktig plassholder byttes til riktig nøkkel; annen verdi gir ingen innsetting.
- Alias og kortform virker. Manglende/tom kilde gir tom klientvariabel.
  Flere tomme regler og aktive/tomme regler på samme destinasjon fungerer.
- Tom/ikke-tom overgang ved apply og gjenopptak fjerner gammel proxy før
  avvisning. Gjenskaping og restart med tom verdi fungerer.
- To miljøer har ulike plassholdere og nøkler. Samme plassholder virker mot
  flere eksplisitt tillatte destinasjoner.
- Ugyldig domene, port, IP, Host, upstream-sertifikat, tvetydige auth-headere,
  TRACE og trailere gir avslag uten upstream-HTTP der policyen krever blokkering.
- DNS-pinning, proxybortfall, direkte tilgang, CA-rotasjon, curl/Python/Node,
  logginnhold og bevaring av agentens hjem ved proxybytte er prøvd.
- Ti SSE-meldinger med ett sekunds intervall kom fortløpende; største målte
  forsinkelse var cirka 41 ms.

`tests/integration/test_lifecycle.py` dekker to images/miljøer, mounts,
read-only, ACL og tilbakekalling, ressursgrenser, socketvern, exec-logginnhold
og gjenopptak etter daemonrestart. `test_uninstall.py` dekker stopp,
eierskapsoverføring, ACL-rydding og sletting av installasjonen uten å endre
andre Docker-instansers identitet.

## Sikkerhetsgjennomgang og grenser

Uavhengige gjennomganger av proxybibliotek, implementasjon, plassholdere og
alias er fullført uten åpne funn som krever retting før merge. Revieweren
brukte syntetiske TLS-tjenester, H1/H2 og rå HTTP/1 for å unngå at klientens
normalisering skjulte feil. TRACE-refleksjon, trailer-/headeraliaser og
sårbare HTTP/2-avhengigheter ble rettet og er dekket av regresjonsprøver.

Behold disse avgrensningene ved videre utvikling:

- Nye Debian-/Docker-/RootlessKit-versjoner og andre arkitekturer trenger
  egne prøver. DNS-videresending er tidligere prøvd mot kontrollert tjeneste.
- Alle krasj-, lås-, ACL- og adressevaktinterleavinger er ikke uttømmende testet.
  Adressevakten stopper etter oppdaget endring, ikke atomisk med nettverksendringen.
- H1-headergrensen kontrolleres etter parsing; containerens ressursgrenser
  begrenser resterende tjenestenektrisiko. Flere tester erstatter ikke dette vernet.
- Codex-prøven bekrefter klientintegrasjon, ikke skjerming av Codex sine egne
  OAuth-data. Den ekte Context7-nøkkelen var bare på proxysiden. Innlogging,
  MCP-oppsett og plassholder var bevart etter proxybytte.
- Restrisiko og tillitsgrenser står i [arkitekturen](architecture.md) og
  [tokenkontrakten](specification.md#api-tokens-på-proxysiden).

## Reproduser laben

Lokale kontroller står i [utviklerveiledningen](development.md).
På en vert med KVM, QEMU, xorriso, curl og SSH:

```sh
scripts/lab/vm.sh prepare
scripts/lab/vm.sh start
scripts/lab/vm.sh ssh 'cloud-init status --wait'
scripts/lab/vm.sh ssh sudo bash -s < scripts/lab/bootstrap.sh
tar --exclude=.git --exclude=.lab --exclude=.venv --exclude=__pycache__ \
  --exclude=.aws --exclude=.codex --exclude=.agents -cf - . | \
  scripts/lab/vm.sh ssh 'mkdir -p /home/developer/agentbox-src && tar -xf - -C /home/developer/agentbox-src'
scripts/lab/vm.sh ssh 'cd /home/developer/agentbox-src && bash scripts/lab/check.sh --uninstall'
scripts/lab/vm.sh stop
```

Kjør labprøver sekvensielt; de endrer felles nettverk og vertsinnstillinger.
Utelat `--uninstall` for å beholde installasjonen til videre labprøver.
Inngangen registrerer plattform, installert kildehash, testpakkehash og image-ID-er
i `.lab/results/platform.json` inne i VM-en. XML-resultater skal ha utførte
tester uten skips; proxyresultatet skal ha `passed: true` og ingen cleanupfeil.
Samle relevante observasjoner i teststatus før dataene fjernes.
`.lab/` er regenererbar VM-disk, SSH-nøkkel og private logger, utelatt fra Git.
Fjern labdata når prøvene er ferdige og VM-en er stoppet.
