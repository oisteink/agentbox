# Spesifikasjon for MVP

Status: MVP godkjent som versjon 1.0 den 30. oktober 2026. Se [teststatus](test-results.md) og
[implementasjonsvalg](decisions-mvp.md) for resultater og presiseringer.

## 1. Formål og omfang

Løsningen skal la én utvikler kjøre kodeagenter i avgrensede Docker-miljøer
på en Linux-maskin. Utvikleren skal enkelt kunne bytte prosjekt og kjøre
flere miljøer samtidig. Eksisterende prosjektmapper monteres direkte, slik
at kodeendringer er tilgjengelige både i editoren på verten og hos agenten.

Arkitekturvalgene er beskrevet i [arkitektur for første versjon](architecture-v1.md).
Denne spesifikasjonen konkretiserer oppførsel og akseptansekriterier.
Kommandonavn og konfigurasjonsformat nedenfor er implementert. Kravene er
normative; [teststatus](test-results.md) angir verifikasjon og kjente
testavgrensninger for versjon 1.0.

MVP-en omfatter:

- Egen tjenestebruker og rootless Docker-instans.
- Eksplisitt prosjektregistrering, ACL-er og bind mounts.
- Oppstart, terminaltilgang, status, logging, stopp og fjerning av miljøer.
- Lukket nettverk og proxy med liste over tillatte destinasjoner.
- Ett medfølgende utviklingsimage og støtte for å velge andre images.
- Verifikasjon av filtilgang, nettverksisolering og ressursgrenser.

## 2. Begreper og tillitsgrenser

| Begrep | Betydning |
| --- | --- |
| Utvikler | Den personlige Linux-brukeren som velger prosjekter og styrer miljøene |
| `agentbox` | Tjenestebrukeren som kjører rootless Docker |
| Prosjekt | En registrert arbeidsmappe med eksplisitt gitt vertstilgang |
| Arbeidsmiljø | Navngitt agentcontainer med valgte mounts, image og nettverkspolicy |
| Kontrollverktøy | CLI som kjøres fra verten og administrerer miljøene |

Agenten og kode den kjører skal behandles som upålitelige. Kontrollverktøy,
Docker-daemon, proxy, images og vertens konfigurasjon inngår i den betrodde
delen av løsningen. Agenten skal ikke kunne endre konfigurasjonen som
bestemmer mounts eller nettverkspolicy.

Rootless containere deler vertens kjerne. MVP-en lover ikke beskyttelse mot
alle kjerne- eller runtime-sårbarheter. Et utbrudd som gir `agentbox` sine
rettigheter kan gi tilgang til alle prosjekter som denne brukeren har fått
tilgang til, og andre filer som allerede er tilgjengelige for lokale brukere.

Domene- og portregler begrenser destinasjoner. De garanterer ikke at data
ikke sendes ut gjennom en tillatt tjeneste.

## 3. Plattform og eierskap

- Første støttede plattform er Linux med systemd, cgroup v2, støtte for
  user namespaces og POSIX ACL-er på prosjektfilsystemet.
- Oppsettet skal opprette eller validere en dedikert `agentbox`-bruker med
  `/var/lib/agentbox` som hjemmekatalog på verten, underordnede UID/GID-områder
  og egen Docker-konfigurasjon. Hjemmekatalogen skal eies av `agentbox` og
  bare være tilgjengelig for denne brukeren og vertsadministrator.
- Docker-data og brukerspesifikk konfigurasjon skal lagres under
  `/var/lib/agentbox`. Flyktige runtime-filer, som daemonens socket, skal
  ligge i brukerens runtime-katalog under `/run/user/<uid>`.
- Vertens `/var/lib/agentbox` skal ikke monteres inn i agentcontainere.
  Containerens hjemmekatalog skal være `/home/agent` i dens eget filsystem.
  Prosjektmapper monteres separat på valgte stier.
- Eksisterende rootful eller personlig Docker-instans skal ikke omkonfigureres.
- Alle kontrollkommandoer skal eksplisitt velge riktig socket eller context
  og kontrollere at daemonen kjører rootless som forventet.
- Docker-socketen skal ikke eksponeres over ubeskyttet TCP eller monteres
  i agentcontainere. Agenten skal ikke få et kontrollgrensesnitt til verten.
- Administrativt oppsett og eventuelle ACL-endringer som krever det, skal
  skilles fra daglig oppstart og bruk.

Transporten er en fast kontrollhjelper kjørt som `agentbox` via avgrenset sudo,
med JSON på stdin og fast lokal Docker-socket. Tilgang til socketen innebærer kontroll over
`agentbox` sine containerressurser og skal begrenses til den betrodde utvikleren.

## 4. Prosjektmapper og ACL-er

### Registrering

Utvikleren skal kunne registrere en eksisterende mappe uten å flytte eller
kopiere den. Kontrollverktøyet skal vise den kanoniske vertsstien og hvilke
rettigheter som gis. Symbolske lenker skal løses ved registrering; et senere
bytte av lenkemål skal ikke automatisk gi tilgang til et annet prosjekt.

Tilgangen skal omfatte:

- Traversering av nødvendige foreldrekataloger, uten å kreve listetilgang.
- Lesing, skriving og traversering av den valgte prosjektmappen.
- ACL-er for eksisterende innhold og standard-ACL-er for nye kataloger og filer,
  slik at utvikleren og `agentbox` kan arbeide på samme filer.

Verktøyet skal ikke bruke rekursiv `chown` eller generelle skriverettigheter
for alle brukere. ACL-endringer skal bevare andre brukeres effektive rettigheter.
Tidligere maskerte biter i rå oppføringer kan trimmes når masken utvides for
utvikleren og `agentbox`; dette skal dokumenteres i brukerflyten.

Prosjektroten skal eies av utvikleren. Overlappende prosjektregistreringer og
eksisterende hardlenkede filer avvises i MVP-en. Andre eiere enn utvikleren
og `agentbox`, samt spesialfiler i prosjektinnholdet, krever manuell avklaring.

Registrering skal være idempotent og ikke følge symbolske lenker eller
underliggende mounts inn i andre vertsmapper ved rekursiv tildeling.
Delvis mislykket tilgangstildeling skal rapporteres som feil.

### Montering og rettigheter

- Et miljø skal kunne få én eller flere registrerte mapper montert på
  eksplisitte, absolutte containerstier.
- Skrivetilgang er standard for kodearbeid; skrivebeskyttet mount skal kunne velges.
- Manglende kildemapper, overlappende mål og reserverte systemstier skal avvises.
- Foreldrekataloger, hjemmekataloger, sockets og hemmeligheter skal ikke følge
  med automatisk. Prosjektinnhold som `.env` blir likevel tilgjengelig hvis det
  ligger i en montert mappe; løsningen gir ikke automatisk hemmelighetsfiltrering.
- Underliggende mounts i et prosjekt skal ikke inkluderes utilsiktet.
- UID 0 i agentcontaineren skal mappe til `agentbox` på verten. Filer som
  agenten oppretter vil normalt eies av `agentbox`.
- Kontrollverktøyet skal kunne kontrollere og reparere nødvendig ACL-tilgang.
  Verktøy som utfører `chmod` eller lager filer med restriktiv modus kan kreve
  slik reparasjon; standard-ACL-er er ikke en ubetinget garanti for alle filer.

### Tilbakekalling

Å stoppe et miljø skal ikke fjerne prosjektregistrering eller ACL-er.
En egen operasjon skal kunne tilbakekalle tilgang. Den skal kreve at berørte
miljøer er stoppet, ta hensyn til andre registrerte prosjekter og bevare
uvedkommende ACL-er på foreldrekatalogene. Åpne filhåndtak kan ellers beholde tilgang.
Tilbakekalling skal ikke slette prosjektfiler eller utføre vilkårlig eierskifte.
Tilgang gjennom prosjektroten skal sperres med en eksplisitt navngitt ACL
for `agentbox`. Innholdets ACL-er og eierskap beholdes. Garantien følger roten,
ikke filer som senere flyttes eller deles gjennom andre stier på verten.

## 5. Arbeidsmiljøer og images

- Hvert miljø skal ha et unikt navn, egen agentcontainer og eget lukket nettverk.
- Minst to miljøer skal kunne kjøre samtidig med ulike prosjektmapper,
  images og nettverkspolicyer.
- Brukeren skal kunne åpne en terminal eller kjøre en kommando i et navngitt miljø.
- Oppstart skal kunne angi image, arbeidskatalog og kommando uten endringer
  i ACL- eller nettverksimplementasjonen.
- Det medfølgende imaget skal ha Bash, Git, CA-sertifikater og et HTTP-verktøy
  for diagnostikk. Første agent er Codex CLI 0.166.0 i `images/dev/`.
- Images må støtte den dokumenterte kjøremodellen med UID 0 og eksplisitt hjem.
  Andre images er valgbare, men ikke automatisk kompatible.
- Agenten skal kjøre uten privilegert modus, vertsnettverk, vertens PID-namespace
  eller ekstra enheter. Linux capabilities skal droppes og privilegieøkning
  blokkeres. En revisjonslåst Moby-seccomp-profil med strengere sperrer mot
  Unix-sockets og alternative socket-syscalls skal brukes. Nødvendige unntak
  må begrunnes og testes særskilt; verktøy som trenger slike sockets er utenfor
  den første imageprofilens kompatibilitetsgaranti.
- CPU-, minne- og prosessgrenser skal være konfigurerbare med dokumenterte
  standardverdier. Oppstart skal feile dersom valgte grenser ikke kan håndheves.

Imagebygging og imagehenting gjøres av den betrodde kontrollsiden og omfattes
ikke av agentens nettverkspolicy. Agenten skal ikke kunne bruke dette som et API
for å starte egne bygg eller hente images.

## 6. Nettverk og proxy

Hvert arbeidsmiljø skal ha en egen proxyinstans, som utgangspunkt Squid.
Proxyen kobles til miljøets lukkede nettverk og et nettverk med ekstern
tilgang. Agentcontaineren kobles bare til det lukkede nettverket.

- Standardpolicy er å avvise alle eksterne destinasjoner.
- Tillatelser skal angi eksakte vertsnavn og porter, eksempelvis
  `api.example.com:443`. Subdomener skal ikke tillates implisitt.
- MVP-en skal støtte HTTP på port 80 og HTTPS via CONNECT på port 443.
  Andre protokoller og porter er utenfor første versjon.
- HTTPS skal ikke dekrypteres i MVP-en. Tillatelsen gjelder dermed hele
  forbindelsen til destinasjonen, uten URL-, metode- eller innholdsfiltrering.
- IP-litteraler og destinasjoner som løses til loopback, private, link-local
  eller øvrige interne adresser skal avvises, også gjennom et tillatt navn.
- Kontrollsiden skal håndtere ekstern navneoppløsning. Agenten skal ikke ha en
  ubegrenset ekstern DNS-kanal. Lokal navneoppløsning som trengs for proxyen
  kan tilbys uten generell videresending av eksterne DNS-spørringer.
- Kontrollsiden skal validere og fastlåse offentlige IPv4-adresser ved oppstart,
  uten DNS-fallback i proxyen. Serverflytting kan kreve eksplisitt gjenoppretting.
  En adressevakt skal stoppe miljøer ved endrede vertsadresser. Nettverksendringer
  på verten er betrodde administrative operasjoner; vakten er ikke en atomisk
  nettverksregel som garanterer sperring i selve endringsøyeblikket.
- IPv6 skal enten håndheve samme policy eller være deaktivert for miljøene.
- Direkte TCP, UDP, QUIC og tilgang til vertsnettverket skal blokkeres,
  også når agenten fjerner alle proxyvariabler eller bruker rå IP-adresser.
- Proxyen skal bare tilby proxytjenesten på miljøets interne grensesnitt.
  Den skal ikke fungere som IP-ruter eller åpen proxy på eksternt grensesnitt.
- Policyfiler skal monteres skrivebeskyttet i proxyen og ikke være tilgjengelige
  for endring fra agenten. Ingen proxyporter publiseres til vert eller LAN.
- Bortfall eller feilkonfigurasjon av proxyen skal stenge utgående tilgang.
- Endret policy skal aktiveres ved eksplisitt `remove` og ny `start`, slik at
  eksisterende tunneler ikke beholder en tilbakekalt tillatelse. Dette sletter
  containerlaget, inkludert innlogging; montert kode beholdes.

Nødvendige domener for agentinnlogging, API-er og pakkeregistre må velges
eksplisitt. Avviste forbindelser skal kunne diagnostiseres uten automatisk
utvidelse av listen over tillatte destinasjoner.

## 7. Brukerflyt og konfigurasjon

CLI-en heter `agentbox`. Opprett miljøfilene for de registrerte prosjektene
før oppstart; filnavnene nedenfor er eksempler:

```sh
agentbox doctor
agentbox project add pacman --path /home/ok/src/pacman
agentbox project add pub-pc --path /home/ok/project/pub-pc
agentbox start pacman-dev --config environments/pacman-dev.yaml
agentbox shell pacman-dev
agentbox start pub-dev --config environments/pub-dev.yaml
agentbox status
agentbox logs pacman-dev
agentbox stop pacman-dev
agentbox remove pacman-dev
```

Miljøkonfigurasjon med to monterte prosjekter:

```yaml
name: pacman-dev
image: agentbox-dev:local
workdir: /home/agent/src/pacman
command: ["bash"]
mounts:
  - project: pacman
    target: /home/agent/src/pacman
    mode: rw
  - project: pub-pc
    target: /home/agent/project/pub-pc
    mode: ro
network:
  allow:
    - host: api.example.com
      port: 443
resources:
  cpus: 2
  memory: 4g
  pids: 512
```

Ressursverdiene viser agentens standardgrenser. Proxyen har faste grenser
på 0,5 CPU, 256 MiB og 128 prosesser. Konfigurasjonen skal valideres før oppstart,
med tydelige feil for ukjente prosjekter, ugyldige verdier og manglende tilgang.
Den skal ikke tillate vilkårlige Docker-flagg som omgår sikkerhetsmodellen.
Hemmelige verdier skal ikke lagres i innsjekkede miljøfiler eller logger.
Eventuelle agentnøkler skal gis eksplisitt per miljø; personlige hjem og
SSH-agent-sockets skal ikke deles automatisk.

## 8. Livssyklus og diagnostikk

- `doctor` kontrollerer socket, daemonidentitet, rootless-modus, datasti,
  Docker-versjon, cgroup v2/systemd og rapportert støtte for ressursgrenser.
  UID/GID-forutsetninger kontrolleres ved installasjon; prosjektets tilgang
  kontrolleres med `project check`. Faktisk håndheving verifiseres i laben.
- Status skal vise miljønavn, tilstand, image, mounts og aktiv nettverkspolicy.
- Logging skal vise agentens utdata og proxyens tillatte/avviste destinasjoner.
  Kontroll- og proxylogger skal ikke inkludere nøkkelverdier eller forespørselsinnhold.
  Agentens egne utdata kan inneholde hemmeligheter; disse loggene skal være
  private og ha størrelsesgrenser, uten løfte om generell innholdsfiltrering.
- Stopp og fjerning skal håndtere gjentatte kall og delvis oppstart uten å
  berøre andre miljøer, instanser eller prosjektfiler.
- Miljøressurser skal merkes slik at opprydding bare fjerner prosjektets egne
  containere og nettverk. Globale Docker-prune-operasjoner skal ikke brukes.
- Kodeendringer i bind mounts skal overleve stopp, fjerning og gjenoppretting.
  Containerlaget, inkludert `/home/agent` og innlogging, beholdes ved stopp
  og gjenopptak med uendret konfigurasjon. Fjerning sletter laget. Separat
  profilvolum er ikke implementert. Endret konfigurasjon eller vertsadresse
  krever eksplisitt fjerning og ny opprettelse.
- MVP-en trenger ikke automatisk gjenoppstart etter vertsreboot.

## 9. Akseptansekriterier

Integrasjonstestene skal bruke midlertidige prosjektmapper og kontrollerte
nettverksdestinasjoner. Forventet blokkering skal bekreftes mot en fungerende
testtjeneste, slik at en død server ikke tolkes som vellykket isolering.

| ID | Verifikasjon |
| --- | --- |
| A1 | Miljøet bruker riktig daemon; feil eller rootful daemon avvises |
| A2 | To miljøer kjører samtidig; stopp og opprydding av ett lar det andre fortsette |
| A3 | Bare valgte vertsmapper er synlige; en kontrollmappe ved siden av prosjektet er utilgjengelig |
| A4 | Begge brukerne kan opprette, redigere, erstatte og slette testfiler; kjørbare filer beholder kjørbarhet |
| A5 | Skrivebeskyttede mounts avviser skriving; kodeendringer overlever fjerning av miljøet |
| A6 | Tillatte HTTP- og HTTPS-destinasjoner fungerer gjennom proxy; andre domener og porter avvises |
| A7 | Direkte IPv4/IPv6 og UDP blokkeres uten proxyvariabler; vert, LAN og andre miljøer er utilgjengelige |
| A8 | DNS gir ingen ubegrenset ekstern kanal; tillatt navn som peker til intern adresse avvises |
| A9 | Stoppet proxy og ugyldig policy gir ingen alternativ utgående tilgang |
| A10 | Agenten kan ikke endre policy, nå Docker-socketen eller opprette egne mounts/nettverk |
| A11 | To images fungerer med samme kontroll-, mount- og nettverksmekanisme |
| A12 | CPU-, minne- og prosessgrenser verifiseres; manglende støtte gir feil |
| A13 | Tilbakekalling av prosjekttilgang bevarer uvedkommende ACL-er og tilgang til andre registrerte prosjekter |

En dokumentert manuell gjennomgang skal i tillegg bekrefte oppsett fra ren
tilstand, prosjektbytte, agentinnlogging og diagnostikk ved avvist trafikk.
MVP-en er ferdig når kravene er implementert, kriteriene er bestått og kjente
begrensninger er dokumentert i bruksveiledningen.

## 10. Utenfor MVP og videre vurdering

- Linked worktrees og håndtering av deres delte Git-metadata.
- Egen vertsbruker eller VM per prosjekt og sterkere runtime som gVisor.
- TLS-inspeksjon, URL-regler, vilkårlig TCP-proxy og utgående SSH.
- GUI, fjernkjøring, flerbrukerplattform og automatisk håndtering av agentkontoer.

Etter MVP-en skal vi sammenligne den testede løsningen med OpenShell og
Docker Sandboxes. Sammenligningen skal vurdere sikkerhetsgrenser,
nettverkspolicy, direkte prosjektmontering, filrettigheter, samtidige miljøer,
imagevalg, plattformkrav og vedlikeholdsarbeid. Resultatet skal brukes til å
avgjøre videre utvikling, gjenbruk av komponenter eller overgang til et alternativ.
