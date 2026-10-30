# Historisk implementeringsplan for MVP

Status: arkivert plan fra utviklingen frem til Agentbox 1.0. Planen beskriver
arbeidsrekkefølge og daværende forslag, og vedlikeholdes ikke som produktspesifikasjon.
Dagens kontrakt står i [Agentbox-spesifikasjonen](../specification.md). Gjennomføringen dokumenteres i
[teststatus](../test-results.md); avklarte tekniske valg står i
[implementasjonsvalg](../decisions.md). Vertsendringer og containerprøver
er utført i en disponibel VM, adskilt fra utviklerens Docker-instans.
Planen er gjennomgått av en uavhengig sub-agent og revidert etter funnene.

## Gjennomføringsstatus per 30. oktober 2026

| Steg | Status |
| --- | --- |
| 0: teknisk prøve | Gjennomført i Ubuntu-VM; versjoner og funn står i teststatus |
| 1: kontrollverktøy | Python-pakke, CLI, YAML-validering, låsing og tilstand implementert |
| 2: installasjon og daemon | Installert og prøvd i VM, inkludert sameksistens med rootful Docker |
| 3: prosjekter og ACL | Registrering, sjekk, reparasjon, tilbakekalling og mounts implementert og prøvd |
| 4: nettverk og proxy | Squid, fastlåst DNS og adressevakt implementert; kontrollerte nettverksprøver bestått |
| 5: livssyklus | Kommandoer, samtidige miljøer, logger og gjenopptak etter daemonrestart prøvd |
| 6: agentimage | Codex 0.166.0 og separat image prøvd; manuell Codex-bruk bekreftet av utvikleren |
| 7: samlet verifikasjon | Labprøver, bruksveiledning og manuell utprøving gjennomført; MVP godkjent som versjon 1.0 |

Åpne prøvepunkter og testavgrensninger finnes i [teststatus](../test-results.md).
Installasjon på utviklerens Debian-vert er gjennomført. Utvikleren godkjente
MVP-en som versjon 1.0 den 30. oktober 2026.
Worktrees og sammenligning med OpenShell/Docker Sandboxes er fortsatt utsatt.

Resten av dokumentet bevarer den opprinnelige planen. Dagens
[produktspesifikasjon](../specification.md) og [arkitektur](../architecture.md)
er videreført fra kravgrunnlaget som planen bygget på.
Formuleringer om åpne beslutninger nedenfor beskriver planleggingstidspunktet.
Løsningene som erstattet forslagene er dokumentert i
[implementasjonsvalgene](../decisions.md): sperre på prosjektroten ved
tilbakekalling, strengere seccomp for Unix-sockets, fastlåst DNS og asynkron
adressevakt. Policyendring krever `remove` og ny `start`; det finnes ingen egen
`restart`-kommando. Agentutdata beskyttes og roteres uten generell filtrering.

## 1. Gjennomføringsprinsipper og teknologivalg

Foreslått implementasjon er en Python-CLI med `argparse`, YAML-konfigurasjon
lest med en sikker parser, og Docker CLI kalt med argumentlister uten shell.
Bash brukes til avgrenset vertsoppsett med eksplisitt feilhåndtering.
Testene bruker pytest og egne integrasjonstester på Linux.

Dette gir et lite kontrollverktøy uten egen daemon eller webtjeneste.
Docker-ressurser opprettes direkte; Compose innføres bare dersom den tekniske
prøven viser en konkret fordel. Python-, Docker-, RootlessKit- og Squid-versjoner
skal fastsettes etter prøven og dokumenteres som testet kombinasjon.

Koden deles i følgende ansvar:

```text
src/agentbox/          CLI, konfigurasjon og kontrollogikk
  config.py           skjemavalidering og normalisering
  projects.py         prosjektregister og ACL-operasjoner
  runtime.py          daemonkontroll og Docker-operasjoner
  policy.py           generering og validering av proxyregler
  state.py            låser, tilstand og gjenoppretting
scripts/              vertsoppsett og installasjon
images/dev/           første utviklingsimage
proxy/                proxyimage og konfigurasjonsmaler
tests/unit/           validering, policy og tilstand
tests/integration/    Linux-, ACL- og nettverkstester
environments/         ufarlige eksempelkonfigurasjoner
docs/                 beslutninger, bruk og testresultater
```

Installasjon og dokumentasjon skal holde kontrollkode og tilstand utenfor
monterte prosjektmapper. Ingen sikkerhetsrelevant kode lastes automatisk
fra et prosjekt som agenten kan endre.

## 2. Steg 0 — teknisk prøve og avklaring av gjennomførbarhet

**Formål:** avdekke forhold som kan endre implementasjonen før vi bygger CLI.
Prøvene skal kjøres på en disponibel Linux-VM med to testbrukere og
midlertidige prosjekter. Utviklerens virkelige prosjektmapper brukes ikke.

### Oppgaver

1. Dokumenter vertsdistribusjon, filsystem, kernel, systemd/cgroup-oppsett og
   tilgjengelige versjoner. Velg én konkret referanseplattform for MVP-en.
2. Opprett rootless Docker som `agentbox`, med hjem `/var/lib/agentbox`,
   egen systemd-brukertjeneste og runtime-katalog under `/run/user/<uid>`.
   Verifiser at dette kan sameksistere med en annen Docker-instans.
3. Prøv en installert, fast kontrollhjelper kjørt som `agentbox` via en
   avgrenset sudo-regel for utvikleren. Hjelperen tar strukturerte operasjoner,
   setter `HOME` og runtime-miljø eksplisitt og bruker en fast lokal socket.
   Ingen generell `sudo docker`, shelltilgang eller socketdeling til agenter.
4. Prøv ACL-er på eksisterende og nye filer, kataloger, `0600`-filer,
   kjørbare filer og atomisk filutskifting. Test identitetene på begge sider.
5. Prøv et internt bridge-nettverk med gateway-modus `isolated`, uten IPv6,
   og en proxy med to grensesnitt. Fastslå faktisk tilgang til vert,
   RootlessKit-gateway, andre miljøer og Docker sin DNS-resolver. Ta med alle
   vertens konkrete interface-adresser og et tillatt navn som peker til
   vertens offentlige adresse med en fungerende testtjeneste.
6. Prøv `bind-recursive=disabled`, privat mount-propagasjon og read-only-mounts.
   Kontroller at underliggende mounts ikke blir med. Test også en Unix-socket
   til en vertstjeneste inne i et delt katalogtre, både før og etter oppstart.
7. Verifiser Squid-regler for eksakte domene/port-par, IP-litteraler og
   DNS-svar med interne adresser, også ved flere eller skiftende DNS-svar.
8. Kontroller faktisk CPU-, minne- og prosessbegrensning for agent og proxy.
   Fastsett dokumenterte standardgrenser på bakgrunn av prøven før steg 5.
   Start prøvene med 2 CPU / 4 GiB / 512 prosesser for agenten og
   0,5 CPU / 256 MiB / 128 prosesser for proxyen; dette er prøveverdier.

### Beslutninger som må lukkes

- **DNS:** utgangspunktet er en statisk intern proxyadresse og en resolver
  uten ekstern videresending for agenten. Docker sin innebygde resolver må
  testes separat. Hvis den gir en ekstern kanal, må vi blokkere den eller
  velge en annen testbar nettverksmekanisme; proxyvariabler løser ikke dette.
- **Proxyadresser:** velg kollisjonsfri subnettallokering og eksplisitt
  ekstern standardrute. Proxyen skal lytte bare internt og ikke videresende IP.
- **Tilbakekalling:** `agentbox` eier agentopprettede filer. Å fjerne en navngitt
  ACL gir ikke i seg selv bortfall av eierrettigheter. Prøven skal avgjøre om
  ønsket tilbakekalling kan oppnås gjennom katalogtilgang alene, eller trenger
  en eksplisitt og avgrenset overføring av eierskap. Eksisterende allmenn
  tilgang kan heller ikke fjernes ved bare å slette våre ACL-er.
  Eventuelle kravendringer skal beskrives før tilbakekalling implementeres;
  vi skal ikke rapportere full tilbakekalling når tilgangen består.
- **Privilegier:** fastslå hvilke ACL-operasjoner utvikleren og `agentbox`
  kan utføre hver for seg. En eventuell root-hjelper krever en egen begrunnet
  operasjonsliste; ingen generell rekursiv privilegert filoperasjon.
- **Unix-sockets i prosjekter:** et katalogmount kan eksponere en vertssocket
  uten et eget socket-mount. En engangsskanning dekker ikke sockets opprettet
  senere. Velg en verifiserbar beskyttelse, eller beskriv en eksplisitt
  avgrensning av hvilke prosjektmapper som støttes og sikkerhetsgarantien dette
  gir. En slik kravendring må avklares før generell prosjektmontering leveres.

**Leveranse:** reproduserbare prøver, testet versjonsmatrise og et kort
beslutningsnotat. Oppdater spesifikasjonen dersom prøven krever endrede krav.
**Ferdig når:** DNS, vertsisolering, UID/ACL, tilbakekalling, kontrolltransport
og ressursgrenser har dokumenterte løsninger eller eksplisitte blokkere.
En registrert blokker betyr at prøven er kartlagt, ikke at avhengig arbeid
er klart til å starte.
En uløst sikkerhetsgrense stopper avhengig implementasjon; kravet svekkes ikke
stille for å få prøven til å passere.

### Avklaringer før avhengige leveranser

Tabellen angir åpne kravavklaringer, ikke allerede vedtatte kravendringer.
Beslutningene skal inn i spesifikasjonen før den aktuelle leveransen kan
regnes som ferdig. Ingen kravendring godtas bare fordi en teknisk prøve feiler.

| Tema | Foreslått avklaring og nødvendig bevis | Blokkerer |
| --- | --- | --- |
| Full tilbakekalling | Skill fjerning av administrerte ACL-er fra dokumentert bortfall av tilgang. Test agentbox-eide filer, eksisterende allmenn tilgang og delte foreldre. Velg avgrenset eierskapsoverføring eller en uttrykkelig snevrere garanti; avklar dette mot spec del 4 og A13 | Tilbakekalling i steg 3 og A13 |
| Logger og hemmeligheter | Skill kontroll-/proxylogger fra agentens egne stdout/stderr. Foreslå at kontrollsiden aldri logger nøkkelverdier, mens agentutdata beskyttes og roteres uten løfte om generell filtrering. Presiser spec del 8 før loggfunksjonen ferdigstilles | Logging i steg 5 og bruksveiledningen |
| Unix-sockets i delte mapper | Demonstrer håndhevet avvisning av vertssockets også etter start, eller avklar begrensningen i støttede prosjektmapper mot spec del 4 og A10 | Generell prosjektmontering i steg 3 og A10 |
| Vertens offentlige adresser | Verifiser at proxyen ikke kan nå vertstjenester gjennom tillatte navn som peker til verten. Velg håndheving som håndterer adresseendringer, eller avklar en snevrere garanti mot A7 | Nettverk i steg 4 og A7 |

## 3. Steg 1 — kontrollverktøy og konfigurasjonsmodell

Avhenger av beslutningene i steg 0.

- Etabler Python-pakke, CLI-inngang, versjonslåste avhengigheter og
  formattering/linting. Dokumenter lokale kommandoer for sjekk og testing.
- Definer skjema for prosjekter, miljøer, mounts, nettverk og ressursgrenser.
  Bruk spesifikasjonens YAML-eksempel som utgangspunkt; avvis ukjente felter.
- Valider navn, eksakte vertsnavn, port 80/443, image, kommando, arbeidskatalog
  og absolutte mål. Avvis dupliserte/overlappende mounts og reserverte stier.
- Avvis implicit hjemmedeling, sockets, enheter og vilkårlige Docker-flagg.
  Deaktiver automatisk montering av eventuelle `VOLUME`-stier fra valgte images
  i konflikt med den eksplisitte mount-modellen, eller avvis slike images.
- Gi hvert oppsett en unik installasjons-ID. Definer stabile etiketter for
  installasjon, miljø og ressursrolle samt hash av aktiv policy.
- Etabler atomiske tilstandsoppdateringer, registerlås og lås per miljø.
  Separate prosesser skal ikke kunne starte samme miljø eller reservere samme
  subnett samtidig. Avvis uforenlig konfigurasjon for et eksisterende miljø.

**Leveranse:** konfigurasjonsvalidering og testbart kontrollgrensesnitt uten
oppstart av agentcontainere.
**Verifikasjon:** enhetstester for ugyldige data, argumentinjeksjon,
navnekollisjoner og avbrutt tilstandsskriving.

## 4. Steg 2 — installasjon, daemon og doctor

- Lag idempotent oppsett for tjenestebruker, `0700`-hjem, UID/GID-områder,
  bruker-systemd og nødvendige avhengigheter. Eksisterende brukere og områder
  valideres; konflikter gir feil fremfor automatisk overstyring.
- Installer kontrollhjelper og avhengigheter på en administratorstyrt sti.
  Sudo-regelen skal peke til denne installasjonen, aldri til en arbeidskopi.
  Bruk et renset miljø, faste programstier og isolert Python-oppstart;
  verken arbeidskatalog, `PYTHONPATH`, `PYTHONHOME` eller brukerinstallerte
  pakker skal kunne påvirke import av kontrollkode.
- Skill systemoppsett som krever root fra daglige operasjoner som `agentbox`.
  Aktiver eventuell linger eksplisitt; dokumenter stopp og avinstallasjon.
- Lag `doctor` med kontroller av socketeier, daemon-ID, rootless-modus,
  mount/ACL-støtte, versjoner og delegerte cgroup-kontrollere.
- Fjern påvirkning fra `DOCKER_HOST`, `DOCKER_CONTEXT` og øvrige miljøvalg
  som ellers kunne sende kommandoer til feil daemon. Kontroller identitet
  før hver muterende Docker-operasjon, også ved gjenoppretting.
- Lag kontrollverktøyets private register og tilstand under `/var/lib/agentbox`.
  Vertens kontrollfiler skal ikke inngå i prosjektregistrering eller mounts.

**Leveranse:** repeterbart oppsett og fungerende `doctor`.
**Verifikasjon:** A1 og grunnlaget for A12; feil daemon, manglende støtte og
delvis installasjon skal gi tydelig feil uten å endre andre Docker-instansers data.

## 5. Steg 3 — prosjektregister, ACL og mounts

- Implementer `project add`, `list`, `check`, `repair` og `revoke`.
  ACL-mutering skal aldri utføres som en skjult del av vanlig miljøstart.
- Lag en tilgangsoversikt før tildeling: kanonisk sti, eier, nødvendige
  foreldrekataloger, ACL-masker og effekt på andre brukere/grupper.
- Registrer hva løsningen faktisk endret. Delte foreldrekataloger og
  overlappende prosjektregistreringer skal ha referanser slik at tilbakekalling
  av ett prosjekt ikke ødelegger et annet.
- Bruk sikker katalogtraversering uten å følge symlinker eller kryssende
  mountpunkter. Avvis ordinære filer med flere hardlenker før ACL-tildeling,
  slik at samme inode utenfor prosjektet ikke gis endrede rettigheter.
  Kontroller lenkeantall ved hver ACL-mutering, også under reparasjon, og
  avbryt ved nye lenker eller identitetsendringer. Test filbytte og stier
  med mellomrom eksplisitt. Dette hindrer utilsiktet ACL-spredning ved våre
  operasjoner; det lover ikke filisolering hvis utvikleren senere oppretter
  hardlenker mellom et delt prosjekt og andre mapper.
  Identifiser prosjektrot ved både kanonisk sti og filsystemidentitet;
  en erstattet rot skal kreve ny validering før montering.
- Stopp alle berørte miljøer under ACL-reparasjon og tilbakekalling, også
  miljøer med read-only-mounts som kan beholde åpne filhåndtak.
  Oppdag endringer under skanning; avbryt heller enn å gi
  tilgang til et ukontrollert nytt mål. Ingen privilegert symlinkfølging.
- Gjenopprett bare administrerte ACL-endringer. Ved samtidige manuelle
  endringer skal verktøyet rapportere konflikt, ikke blindt gjenopprette en
  gammel ACL eller maske som fjerner andres nye rettigheter.
- Bygg mounts med eksplisitt kilde/mål, `rprivate` og uten recursive mounts.
  Manglende kilde skal ikke opprettes automatisk. Bruk isolerte testmapper.
- Avvis eksisterende Unix-sockets og andre spesialfiler i prosjekttrær.
  Håndhev i tillegg den vedtatte løsningen fra steg 0 for sockets som dukker
  opp etter oppstart; skanning alene skal ikke omtales som sikkerhetsgrense.

**Leveranse:** to registrerte prosjekter som kan deles uavhengig, med
testet reparasjon og tilbakekalling etter modellen fra steg 0.
**Verifikasjon:** A3–A5 og A13, inkludert eksisterende ACL-er, nye filer,
restriktive filmoduser, symlinker, hardlenker og nestede mounts. En avvist
hardlenket fil skal beholde uendret ACL også via lenken utenfor prosjektet.
Test tilbakekalling med en read-only-leser som holder et åpent filhåndtak;
alle berørte miljøer skal være stoppet før operasjonen kan fullføres.

## 6. Steg 4 — nettverk og proxy med sperret standardtilgang

- Lag proxyimage, versjonslåst Squid-konfigurasjon og policygenerator.
  Tillatelser skal være par av eksakt vertsnavn og port; ingen utilsiktet
  kombinasjon av alle navn med alle porter eller implisitte subdomener.
- Blokker IP-litteraler og ikke-offentlige destinasjonsadresser før tillatelser.
  Håndhev også beslutningen fra steg 0 om vertens egne offentlige adresser.
  Test DNS-endringer og blandede svar mot Squid-versjonen fra steg 0.
- Opprett et lukket nettverk og et separat eksternt nettverk per miljø.
  Implementer vedtatt DNS-løsning og subnettallokering. IPv6 er deaktivert
  i MVP-en og skal også testes for faktisk blokkering.
- Proxyen får ingen prosjektmapper, hemmeligheter eller Docker-socket.
  Policyen monteres read-only fra kontrollsidens private tilstand.
- Agenten får kun det lukkede nettverket; ingen publiserte porter.
  Proxyens interne lytteadresse, eksterne rute og manglende IP-videresending
  kontrolleres etter opprettelse.
- Valider policy med Squid før oppstart. Ikke start agenten før proxyen er
  klar og sikkerhetskonfigurasjonen er kontrollert. Begrens proxyressurser og
  loggstørrelse. Avslag skal logges som destinasjon og årsak uten full URL.

**Leveranse:** et lite testmiljø som demonstrerer tillatt og blokkert trafikk.
**Verifikasjon:** A6–A10; inkluder proxybortfall, tom/ugyldig policy,
omdirigering til avvist domene, fjernede proxyvariabler og andre miljøers proxyer.

## 7. Steg 5 — livssyklus og samtidige miljøer

- Implementer `start`, `shell`, `exec`, `status`, `logs`, `stop`, `remove`
  og kontrollert gjenoppretting med ny konfigurasjon.
- Skill miljøets levetid fra terminalsesjonen: et lite init/oppholdsprogram
  holder miljøet tilgjengelig; valgt kommando kjøres med korrekt TTY,
  arbeidskatalog, signalhåndtering og exitkode. Å lukke terminalen skal ikke
  stoppe andre jobber eller miljøer utilsiktet.
- Opprett ressurser i fast rekkefølge: validering, nettverk, proxy og agent.
  Registrer ressurs-ID-er fortløpende. Feil skal utløse avgrenset opprydding.
- Bruk UID 0, `HOME=/home/agent`, droppede capabilities, `no-new-privileges`,
  standard seccomp og verifiserte ressursgrenser. Ikke overfør vertens miljø
  eller credentials automatisk.
- Håndter eksplisitte agentnøkler per miljø fra en privat fil eller annen
  dokumentert lokal kilde. Ikke legg nøkkelverdier i argumenter, innsjekkede
  konfigurasjoner, status eller kontrollverktøyets logger.
- Avklar logggrensen: agentens egne stdout/stderr kan inneholde det agenten
  skriver, også hemmeligheter. Ingen garanti om generell innholdsredigering;
  beskytt tilgang og loggrotasjon, og presiser dette i bruksveiledningen.
- Restart ved policyendring skal avslutte gamle tunneler og tilknyttede
  prosesser før nye tillatelser tas i bruk. Agenten skal ikke beholde gammel
  proxy etter en oppdatering.
- Stopp/fjerning skal kreve samsvar mellom ressurs-ID og etiketter, tåle
  gjentatte kall og håndtere krasj mellom Docker-operasjon og tilstandsskriving.
  Ingen global prune eller sletting av prosjektfiler.

**Leveranse:** to samtidige brukbare miljøer med separat livssyklus.
**Verifikasjon:** A2, A5, A9 og A10, samt samtidige start/stopp-kall,
avbrutt oppstart, foreldreløse ressurser og gjenoppretting etter daemonrestart.

## 8. Steg 6 — utviklingsimage og praktisk agentbruk

- Bygg et lite utviklingsimage med Bash, Git, CA-sertifikater og curl,
  samt ett eksplisitt valgt agentverktøy. Velg og dokumenter agent og
  nødvendige API-/innloggingsdomener før denne leveransen starter.
- La en imageprofil beskrive image og oppstartskommando; felles kode skal
  ikke inneholde verktøyspesifikk ACL- eller nettverkslogikk.
- Bruk et annet minimalt image for å verifisere imagevalg uten kodeendringer.
  Test at images med uønskede standardvolumer eller entrypoints avvises eller
  kjøres med en eksplisitt sikker profil.
- Prøv en vanlig Git-klone, editorendringer fra verten, filendringer fra
  agenten, prosjektbytte og to samtidige miljøer. Dokumenter Git-eierskap og
  eventuelt snevert `safe.directory`-oppsett for konkrete mounts; ikke `*`.
- Dokumenter at imagebygging/henting skjer på kontrollsiden og at pakkehenting
  inne i miljøet fortsatt følger agentens nettverkspolicy.

**Leveranse:** en ende-til-ende-demonstrasjon med reelt agentverktøy.
**Verifikasjon:** A4 og A11, eksplisitt innlogging og et enkelt kodearbeid
uten tilgang til vertens øvrige brukeroppsett.

## 9. Steg 7 — samlet verifikasjon og bruksveiledning

Opprett en disponibel referanse-VM med en utviklerbruker, `agentbox`, to
prosjekter og kontrollfiler som ikke skal være tilgjengelige. Testfixture for
nettverk skal ligge utenfor agentnettverket og ha uavhengig observasjon av
DNS-spørringer og forbindelser. Testene skal vise at destinasjonene fungerer
fra en kontrollklient før blokkering godtas som testresultat.

Offentlig HTTPS testes mot en kontrollert offentlig adresse med gyldig
sertifikat. Dersom en lokal lab brukes til andre prøver, skal eventuelle
testunntak holdes utenfor produksjonspolicyen. Ikke svekk blokken mot private
adresser for å få nettverkstestene til å virke.

| Kriterier | Hovedleveranse | Samlet kontroll |
| --- | --- | --- |
| A1 | Steg 2 | Feil socket/daemon, rootful-modus og private kontrollfiler |
| A2 | Steg 5 | To miljøer og uavhengig, samtidig livssyklus |
| A3–A5 | Steg 3 og 5 | Synlighet, filoperasjoner, read-only og bevaring av kode |
| A6–A9 | Steg 4 og 5 | Tillatelser, DNS, direkte trafikk, proxyfeil og policyrestart |
| A10 | Steg 4 og 5 | Ingen kontrolltilgang, policyendring eller nye vertsressurser fra agenten |
| A11 | Steg 6 | To imageprofiler med felles sikkerhetsmekanisme |
| A12 | Steg 0, 2 og 5 | Faktiske cgroup-grenser, også for proxyen |
| A13 | Steg 0 og 3 | Tilbakekalling og bevaring av andre ACL-er/prosjekter |

Automatiser sikkerhetskritiske tester. Bruk kontrollerte testprosesser for
ressursprøver og avgrens belastningen til test-VM-en. Registrer miljø,
kommandoer, forventning og resultat; en hoppet over test er ikke bestått.

Lag README med installasjon, førstegangsoppsett, prosjektregistrering,
miljøkonfigurasjon, innlogging, prosjektbytte, ACL-reparasjon, tilbakekalling,
feilsøking og avinstallasjon. Dokumenter lagring som overlever stopp og hva
som slettes med containeren. Avinstallasjon skal ikke slette kode eller
automatisk fjerne brukeren mens den fortsatt eier prosjektfiler.

**Ferdig når:** A1–A13 er bestått på referanseplattformen, manuell
agentgjennomgang er dokumentert, sikkerhetsavvik er lukket og kjente
begrensninger er tydelige. Funksjoner på andre plattformer merkes som utestet.

## 10. Rekkefølge, stoppunkter og senere arbeid

Avhengigheter: steg 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7.
Testene bygges sammen med leveransene; steg 7 samler dem fra et rent oppsett.
Hvert steg kan deles i små commits med relevant dokumentasjon og verifikasjon.

De første stoppunktene er gjennomførbarhet av nettverk/DNS og faktisk
tilbakekalling av filtilgang. Hvis de krever endret arkitektur, oppdateres
beslutningsnotatet og spesifikasjonen før videre avhengig arbeid.

Etter godkjent MVP sammenligner vi erfaringer og målte egenskaper med
OpenShell og Docker Sandboxes. Worktrees og sterkere isolering vurderes
deretter. Ingen av disse inngår i MVP-leveransen.

## Teknisk grunnlag for prøvene

- [Docker nettverk og DNS](https://docs.docker.com/engine/network/)
- [Gateway-moduser](https://docs.docker.com/engine/network/port-publishing/#gateway-modes)
- [Bind mounts og underliggende mounts](https://docs.docker.com/engine/storage/bind-mounts/)
- [POSIX ACL og eierrettigheter](https://man7.org/linux/man-pages/man5/acl.5.html)
