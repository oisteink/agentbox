# Teststatus for Agentbox

Resultater fra 6. november 2026. Kravdekning og åpne verifikasjonshull står i
[teststrategien](testing.md). Beståtte prøver gjelder det angitte oppsettet.

## Plattform og resultater

Lab: Ubuntu 24.04.5 amd64, kernel 6.8.0-147-generic, systemd/cgroup v2,
rootless Docker 29.9.3, Python 3.12.3 og pytest 9.0.3. Proxyimaget bruker
Debian 13, Go 1.27.3 og goproxy v1.9.2. Laben bygger Codex 0.166.0,
OpenCode 1.19.5, Claude Code 2.1.316 og smoke-imaget.

| Kontroll | Resultat |
| --- | --- |
| Python-enhetstester, Python 3.13 / pytest 9.0.3 | 294 testtilfeller bestått |
| Ruff lint/format, Bash-syntaks og gofmt | Bestått |
| Go race og vet | Bestått, HTTP/1 og HTTP/2 |
| govulncheck v1.9.0, Go 1.27.3 | Ingen sårbarheter som kan nås |
| C4-kilde og bilder | SVG/PNG rendret; etiketter, lesbarhet og lenker kontrollert |
| Dokumentasjon | CLI, skjema, lagring, proxybygg, installasjon og C4 kontrollert mot kode; lokale lenker og eksempler validert |
| Wheel | Dockerfile-maler, .dockerignore, launcher og sesjonsmodul verifisert |
| Installasjon og imagebygg i VM | Bestått; installerte filer sammenlignet med kilde |
| Mounts/volumer | Katalog-ACL, ro/rw, profil/HOME-volumer, revoke/fix, samtykke, stoppede brukere og retry bestått |
| Installert CLI og oppsett | 60 scenarier bestått: 59 i hovedløp og én målrettet prøve, ingen skips |
| Installert proxy | 25 kontroller bestått, ingen oppryddingsfeil |
| Avinstallasjon | Bestått; annen rootful Docker-instans og kontrollvolum bevart |

Installert kildehash: `af9655e720eedba4537ceae7801f33dc50ec590f7f7575a465e8172086d75bed`.
Test-/skripthash: `17be1c21e74c258e46695f73b1afa14e784db904a5a2ba9651af022ccdac926e`.
Hashene beregnes av labskriptets plattformkontroll.

Lokale kontroller bruker `scripts/check.sh`; laben bruker `scripts/lab/check.sh`
og avinstallasjonsprøven til slutt med `AGENTBOX_UNINSTALL_LAB=1`.
Labprøvene bruker syntetiske tokens,
uten ekte nøkler eller modellkall. En separat manuell Codex/Context7-prøve
31. oktober fullførte ett read-only modellkall med `resolve-library-id`.

## Verifisert omfang

- Installasjon: proxyimage ved første oppsett, gjenbruk under reinstallasjon
  med en stoppet container og feil ved ugyldig kilde når imaget mangler.
- Imageoppskrifter: lokal default/prioritet, selvstendige kopier med skjulte
  filer og lenker, endringsdeteksjon, automatisk bygg og exec-oppstart. Tagflytting
  beholder bygg-/fjerningssperren; stoppet image-/profilbytte gir ny agent-ID
  og bevarer katalog-/volumdata. Ugyldig ny mount beholder det stoppede laget.
  Exec og pending start beholder en stoppet proxy. Reinstallasjon gjenoppretter
  medfølgende maler og beholder lokale oppskrifter.
- Lokale prøver: konfigurasjon, ACL-regler, policy, tokenaliaser, plassholdere,
  editorvalg, binær kontrollprotokoll og sikker utpakking av byggkontekst.
- Installert CLI: to images/miljøer, COPY/.dockerignore, bygg/fjerning under
  kjørende og stoppet bruk, editorens inn-/utdata og exitkode, mounts,
  read-only, ACL/tilbakekalling, socketvern, ressursgrenser og exec-logger.
- Automatisk livssyklus: start og exec kjører i terminalen, begge
  avslutningsrekkefølger for to aktive kjøringer, sent og repetert keep-running,
  og eksplisitt stop med en forsinket gammel finally. Ny kjøreperiode med
  samme container-ID beholdes. Klient-/helperkrasj oppdages av watcher;
  keep-running bevares, øvrige siste kjøringer stoppes eller fjernes.
- Ikke-persistent miljø: exitkode 0/17, rent hjem ved neste start, bevarte
  mountfiler, delte aktive kjøringer og stop-fjerning. Stoppet lag etter avbrutt
  fjerning erstattes. Lokale feilprøver dekker startup, queued SIGINT,
  generation-binding, ukjent proc-observasjon og launch_unknown som overlever stop.
- Run: parallelle unike instanser sammen med ordinært miljø, status/logs/stop,
  exitkode 0/17, stdout/stderr, PTY, input og Ctrl-C. Bare egen instans fjernes;
  registrerte katalog-/volumdata beholdes. Katalog-FD-prøve viser at gammel
  output ikke skriver i et fjernet og gjenskapt miljøs katalog.
- Utskrift: mennesketabell, JSON-parserfeil/hjelp, konfigurasjonsfeil og
  kommandofeil med exitkode i sluttresultatet. Installert stdin/stdout/stderr
  med 200 kB i begge retninger, tidlig stdin-stenging, delt/ugyldig UTF-8,
  editor med input/exitstatus og Ctrl-C gjennom sudo med full opprydding.
  Lokale prosesser dekker ventende input, stor pipet input gjennom setup-retry,
  avbrudd før input åpnes og ugyldig/ufullstendig protokoll.
- Mounts: navngitt profilvolum gjennom remove/run/imagebytte, eksplisitt HOME i
  ikke-persistent miljø, ro/rw, revoke med aktive brukere og åpent håndtak,
  fix uten reaktivering og sletting med stoppede volumbrukere. Katalog-remove
  bevarer data, eierskap og operatørtilgang; symlinkmål/andre ACL-er beholdes.
  Manglende/fremmede volumer, delvis katalogrydding og faktisk retry etter
  manglende traversering er prøvd. Lokale avbruddsprøver dekker ACL-pass,
  forget, delvis miljøfjerning og volumsletting før registercommit.
- Livssyklus: containerlag ved stopp/start og daemonrestart, filer i katalogmounts
  ved remove, samt eierskap/ACL ved avinstallasjon. Nestede mounts og
  beskyttede filer utenfor mountet inngår i prøvene.
- Proxy: eksakt tokenutskifting, aliaser, aktive/tomme regler, flere miljøer,
  HTTP/1 og HTTP/2, auth-headere/trailere, Host/SNI, upstream-sertifikater,
  DNS-pinning, private adresser, direkte tilgang og proxybortfall.
- Proxyens klientintegrasjon: CA for curl/Python/Node, SSE, CA- og nøkkelrotasjon,
  logginnhold og bevart agenthjem ved proxybytte. Start etter proxy-stopp
  beholder avvist trafikk til eksplisitt apply.

## Begrensninger

- Minste Debian-versjon er ikke fastsatt. Full installert akseptanse av
  Go-proxyen på Debian og arm64 gjenstår.
- Kontrollert UDP/DNS, vert/LAN, alternative socketsyscalls, mount-forsøk og
  skriving til alle kontrollfiler trenger oppdaterte prøver.
- Vertsreboot, alle delvise oppstartssteg, eventhistorikk under press,
  samtidige ACL-endringer, adressevakt, signaler med keep-running, dynamisk
  terminalstørrelse og CPU-/OOM-oppførsel er ikke uttømmende prøvd.
- Ukjent launch og prosessobservasjonsfeil er feilinjisert lokalt. Full VM-
  feilinjeksjon av backend-launch og samtidige nødstoppsgarantier gjenstår.
- Adressevakten reagerer etter oppdaget endring; den er ikke atomisk med
  nettverksendringen. H1-headergrensen kontrolleres etter parsing, med
  ressursgrenser som vern mot resterende tjenestenektrisiko.
- Codex-prøven viser klientintegrasjon. Codex sine OAuth-data og hemmeligheter
  i filer i katalogmounts omfattes ikke av proxyens tokenbeskyttelse. En tillatt tjeneste
  kan returnere en ekte nøkkel i responsen; svar skannes ikke etter hemmeligheter.

OpenCode- og Claude Code-malene er bygget, og `--version` virker i Agentbox-
isoleringen. Lokale prøver dekker CLI-valg, kopiering, arkivering, miljøfiler
og samsvar mellom API-regel og credential-destinasjon. TUI, innlogging,
modelltrafikk og verktøyenes bruk av CA/tokenbytte er ikke prøvd.

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
