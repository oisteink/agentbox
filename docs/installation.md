# Installasjon av Agentbox 1.0

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
sudo scripts/install.sh --operator "$(id -un)"
agentbox doctor
agentbox build-images
```

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

Bruk `agentbox remove NAVN` og tilbakekall prosjekter før avinstallasjon.
Stopp deretter Docker-brukertjenesten og `agentbox-watch.service` for den
konkrete tjenestebrukeren. Fjern prosjektets sudo-regel, entrypoints og
`/opt/agentbox` først når miljøene er avviklet.

Ikke slett `agentbox`-brukeren, hjemmet eller journalen under
`/var/lib/agentbox-operator` automatisk: brukeren kan fortsatt eie prosjektfiler,
og journalen kan være nødvendig for å rydde ACL-er. Agentbox 1.0 har ingen automatisk
brukersletting eller destruktiv fullavinstallasjon.
