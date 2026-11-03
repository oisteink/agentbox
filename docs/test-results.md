# Teststatus for Agentbox

Resultater fra 2. og 3. november 2026. Kravdekning og åpne verifikasjonshull står i
[teststrategien](testing.md). Beståtte prøver gjelder det angitte oppsettet.

## Plattform og resultater

Lab: Ubuntu 24.04.5 amd64, kernel 6.8.0-147-generic, systemd/cgroup v2,
rootless Docker 29.9.2, Python 3.12.3 og pytest 9.0.3. Proxyimaget bruker
Debian 13, Go 1.27.3 og goproxy v1.9.2. Laben bruker Codex 0.166.0 og smoke-imaget.

| Kontroll | Resultat |
| --- | --- |
| Python-enhetstester, Python 3.13 / pytest 9.0.3 | 178 bestått |
| Ruff lint/format, Bash-syntaks og gofmt | Bestått |
| Go race og vet | Bestått, HTTP/1 og HTTP/2 |
| govulncheck v1.9.0, Go 1.27.3 | Ingen sårbarheter som kan nås |
| Wheel | Dockerfile-maler og Codex-launcher inkludert |
| Installasjon og imagebygg i VM | Bestått; installerte filer sammenlignet med kilde |
| Installert CLI og oppsett | 14 scenarier bestått, ingen skips |
| Installert proxy | 24 kontroller bestått, ingen oppryddingsfeil |
| Avinstallasjon | Bestått; annen rootful Docker-instans bevart |

Lokale kontroller bruker `scripts/check.sh`; laben bruker
`scripts/lab/check.sh --uninstall`. Labprøvene bruker syntetiske tokens,
uten ekte nøkler eller modellkall. En separat manuell Codex/Context7-prøve
31. oktober fullførte ett read-only modellkall med `resolve-library-id`.

## Verifisert omfang

- Installasjon: proxyimage ved første oppsett, gjenbruk under reinstallasjon
  med en stoppet container og feil ved ugyldig kilde når imaget mangler.
- Lokale prøver: konfigurasjon, ACL-regler, policy, tokenaliaser, plassholdere,
  editorvalg, binær kontrollprotokoll og sikker utpakking av byggkontekst.
- Installert CLI: to images/miljøer, COPY/.dockerignore, bygg/fjerning under
  kjørende og stoppet bruk, editorens inn-/utdata og exitkode, mounts,
  read-only, ACL/tilbakekalling, socketvern, ressursgrenser og exec-logger.
- Livssyklus: containerlag ved stopp/start og daemonrestart, prosjektfiler
  ved remove, samt eierskap/ACL ved avinstallasjon. Nestede mounts og
  beskyttede filer utenfor prosjektet inngår i prøvene.
- Proxy: eksakt tokenutskifting, aliaser, aktive/tomme regler, flere miljøer,
  HTTP/1 og HTTP/2, auth-headere/trailere, Host/SNI, upstream-sertifikater,
  DNS-pinning, private adresser, direkte tilgang og proxybortfall.
- Proxyens klientintegrasjon: CA for curl/Python/Node, SSE, CA- og nøkkelrotasjon,
  logginnhold og bevart agenthjem ved proxybytte.

## Begrensninger

- Minste Debian-versjon er ikke fastsatt. Full installert akseptanse av
  Go-proxyen på Debian og arm64 gjenstår.
- Kontrollert UDP/DNS, vert/LAN, alternative socketsyscalls, mount-forsøk og
  skriving til alle kontrollfiler trenger oppdaterte prøver.
- Krasj, samtidige låser/ACL-endringer, adressevakt, vertsreboot, terminalsignaler,
  dynamisk terminalstørrelse og CPU-/OOM-oppførsel er ikke uttømmende prøvd.
- Adressevakten reagerer etter oppdaget endring; den er ikke atomisk med
  nettverksendringen. H1-headergrensen kontrolleres etter parsing, med
  ressursgrenser som vern mot resterende tjenestenektrisiko.
- Codex-prøven viser klientintegrasjon. Codex sine OAuth-data og hemmeligheter
  i prosjektfiler omfattes ikke av proxyens tokenbeskyttelse. En tillatt tjeneste
  kan returnere en ekte nøkkel i responsen; svar skannes ikke etter hemmeligheter.

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
