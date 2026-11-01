# Teststatus for Agentbox

Sist verifisert 1. november 2026 på `feat/credential-proxy`. Resultatene
nedenfor gjelder observerte prøver, ikke en garanti for alle feiltilstander.

## Miljø og resultater

VM: Ubuntu 24.04.5, amd64, kernel 6.8.0-147-generic, rootless Docker 29.9.2
og systemd/cgroup v2. Proxyimaget bruker Debian 13, Go 1.27.3 og goproxy v1.9.2.
Codex CLI 0.166.0 er prøvd. Ny Go-proxy er ikke prøvd på Debian-verten;
minste Debian-versjon er ikke fastsatt.

| Kontroll | Resultat | Sist kjørt |
| --- | --- | --- |
| Python-enhetstester | 137 bestått | 1. november |
| Ruff lint/format, Bash-syntaks og gofmt | Bestått | 1. november |
| Go race-deteksjon og vet | Bestått, HTTP/1 og HTTP/2 | 1. november |
| govulncheck v1.9.0 med Go 1.27.3 | Ingen sårbarheter som kan nås | 1. november |
| Installer og bygg produksjonsimages i VM | Bestått | 1. november |
| Installert proxyakseptanse | Bestått med syntetiske nøkler | 1. november |
| Installert CLI-livssyklus | 1 bestått, 21,99 sekunder | 1. november |
| Codex med ChatGPT device-login og Context7 | Én read-only modellkjøring fullførte resolve-library-id | 31. oktober |
| Avinstallasjon i disponibel VM | Bestått; øvrig rootful Docker bevart | 31. oktober |

Avinstallasjon er ikke kjørt på nytt etter aliasendringen. Installasjon og
Codex-bruk fra 1.0/1.0.1 er tidligere prøvd manuelt på utviklerens Debian-vert.

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
read-only, ACL og tilbakekalling, ressursgrenser, socketvern, private logger
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
scripts/lab/vm.sh ssh 'sudo bash /home/developer/agentbox-src/scripts/install.sh --operator developer'
scripts/lab/vm.sh ssh 'agentbox build-images'
scripts/lab/vm.sh ssh 'bash /home/developer/agentbox-src/scripts/lab/build-images.sh'
scripts/lab/vm.sh ssh 'sudo python3 /home/developer/agentbox-src/scripts/lab/credential_proxy.py'
scripts/lab/vm.sh ssh 'cd /home/developer/agentbox-src && AGENTBOX_LAB=1 python3 -m pytest -q tests/integration/test_lifecycle.py'
scripts/lab/vm.sh stop
```

Kjør labprøver sekvensielt; de endrer felles nettverk og vertsinnstillinger.
Avinstallasjonsprøven skal kjøres sist etter [egen oppskrift](development.md#avinstallasjonsprøve).
`.lab/` er regenererbar VM-disk, SSH-nøkkel og private logger, utelatt fra Git.
Fjern labdata når prøvene er ferdige og VM-en er stoppet.
