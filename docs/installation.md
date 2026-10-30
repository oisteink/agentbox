# Installasjon av Agentbox 1.0.1

Kjør installasjonen fra repoet på Linux-verten som skal kjøre agentmiljøene.
Daglig bruk skjer deretter som utvikleren, uten `sudo agentbox`.

## Forutsetninger og installasjon

Referanseplattformen er Ubuntu 24.04 med systemd, cgroup v2, POSIX ACL,
user namespaces og rootless Docker. Python 3.12 eller nyere kreves.
Koden krever Docker 28 eller nyere; bare 29.9.2 er testet. Installer
[Docker Engine og rootless extras](https://docs.docker.com/engine/security/rootless/)
før prosjektets installer kjøres. Andre nødvendige pakker på Ubuntu:

```sh
sudo apt-get install acl uidmap dbus-user-session slirp4netns python3-venv sudo iproute2
sudo scripts/install.sh
agentbox doctor
agentbox build-images
```

Utviklerbrukeren hentes fra `SUDO_USER`, altså brukeren som kjører `sudo`.
For å installere for en annen bruker, oppgi navnet eksplisitt:

```sh
sudo scripts/install.sh --operator annen-bruker
```

Ved direkte kjøring som root må `--operator` oppgis. Root og `agentbox`
kan ikke velges som utvikler. Vis alternativene med `scripts/install.sh --help`.

Installeren oppretter `agentbox` med hjem `/var/lib/agentbox`, installerer
kontrollkode under `/opt/agentbox` og gir den valgte utvikleren tilgang til
en fast kontrollhjelper gjennom sudo. Den installerer en privat Python-venv
med PyYAML 6.0.2 og trenger pakketilgang ved første oppsett.

Docker-pakker installeres ikke av prosjektinstalleren. Andre Docker-instansers
konfigurasjon og context endres ikke. CPU-/minne-/prosesskontroll delegeres til
den konkrete systemd-brukerinstansen for `agentbox`.
Stopp miljøene før reinstallasjon eller oppdatering av kontrollverktøyet.

## Velg adresseområde

Agentbox trenger to ledige `/28`-subnett per miljø. Standardområdet er
`172.28.0.0/16`. Andre Docker-instansers nettverk, LAN og VPN-ruter kan
kollidere med det. Kontroller vertens ruter med `ip -4 route show table all`.

Ved feilen `No two collision-free /28 subnets` velger administrator et annet
ledig privat IPv4-område i `network_pool` i `/etc/agentbox/settings.json`.
For eksempel kan `172.30.0.0/16` brukes dersom det er ledig på den aktuelle
verten. Ikke slett andre nettverk for å frigjøre Agentbox sitt standardområde.
Installeren bevarer adressevalget ved reinstallasjon.

## Kontroller installasjonen

`agentbox doctor` skal rapportere `rootless: true`, riktig daemon-ID og
`cgroup: systemd`. `agentbox build-images` skal gi image-navnene
`agentbox-dev:local` og `agentbox-proxy:local`. `agentbox status` kan vise `{}`
før første miljø er opprettet.

Fortsett med [prosjektregistrering og første miljø](usage.md).
Versjonsmatrise og skillet mellom labprøver og manuell Debian-utprøving står i
[teststatus](test-results.md).

## Avinstallasjon

Kjør fra repoet, på samme måte som installasjonen. Se omfanget uten å endre
installasjonen:

```sh
sudo scripts/uninstall.sh --dry-run
```

Avinstaller hele Agentbox-installasjonen:

```sh
sudo scripts/uninstall.sh
```

Skriptet bruker systemets Python og trenger ikke den installerte CLI-en.
Det varsler om at
miljøene stoppes og at containerhjem, innlogging og images slettes. Deretter:

1. Stoppes den dedikerte brukerinstansen, Docker og øvrige agentbox-prosesser.
2. Overføres agentbox-eide filer, kataloger og selve symlinkene i registrerte
   prosjekter til utviklerens UID og primærgruppe. Dette omfatter også
   tilbakekalte prosjekter som fortsatt finnes i registeret.
3. Fjernes tjenestebrukerens tilgangs- og standard-ACL-er. Andre ACL-oppføringer
   og masker beholdes. Foreldrenes opprinnelige ACL gjenopprettes når den ikke
   er endret manuelt; ellers fjernes bare tjenestebrukerens oppføring.
4. Fjernes tjenestebrukeren, dens egne UID/GID-områder, udelte gruppe,
   systemd-oppsett, sudo-regel, programmer, completion og Agentbox sine data.

Prosjektinnhold og miljøfiler utenfor installasjonen beholdes. Andre
Docker-instansers brukere, konfigurasjon og data berøres ikke. Docker-pakkene
avinstalleres ikke.

Filryddingen følger ikke symlinker og krysser ikke nestede mounts.
Endret prosjektrot, manglende aktiv prosjektmappe eller berørte hardlenker gir
feil før brukeren og installasjonsdataene slettes. Rett årsaken og kjør
`sudo scripts/uninstall.sh` igjen. Miljøene kan allerede være stoppet ved en slik feil.
Gamle tilbakekalte prosjekter som er slettet, hoppes over.
