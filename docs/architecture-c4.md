# Agentbox på C4 nivå 1 og 2

Diagrammene viser dagens MVP. C1 viser systemet og omgivelsene; C2 viser
kjørbare deler, datalagre og forbindelsene mellom dem.

En C4-container betyr et program eller et datalager. Begrepet er bredere enn
en Docker-container: CLI-en og kontrollhjelperen er også C4-containere.
Alle interne deler kjører på samme Linux-vert. Test-VM-en er et labmiljø og
inngår ikke som et krav i produktarkitekturen.

## C1 systemkontekst

![C1: Agentbox og omgivelsene](diagrams/agentbox-context.svg)

<details>
<summary>PlantUML-kilde</summary>

```plantuml
@startuml agentbox-context
!include <C4/C4_Context>
LAYOUT_LEFT_RIGHT()
title Agentbox - C1 systemkontekst

Person(developer, "Utvikler", "Velger prosjekter og agentverktøy; arbeider i ett eller flere miljøer.")
System(agentbox, "Agentbox", "Kjører kodeagenter med avgrenset filtilgang og kontrollert nettverkstilgang.")
System_Ext(workspace, "Lokalt utviklingsmiljø", "Utviklerens editor og eksisterende prosjektmapper.")
System_Ext(models, "Modelltjeneste", "For eksempel OpenAI; brukerens valgte agentkonto.")
System_Ext(development, "Kode- og pakketjenester", "For eksempel GitHub og pakkeregistre; bare når destinasjonene er tillatt.")
System_Ext(build, "Image- og byggeregistre", "Docker-images og avhengigheter for betrodd imagebygging.")

Rel(developer, agentbox, "Registrerer mapper, konfigurerer og bruker agentmiljøer")
Rel(developer, workspace, "Redigerer kode i egen editor")
BiRel(agentbox, workspace, "Deler eksplisitt valgte prosjektmapper")
Rel(agentbox, models, "Sender agentforespørsler når destinasjonen er tillatt")
Rel(agentbox, development, "Henter eller sender data når destinasjonen er tillatt")
Rel(agentbox, build, "Henter images og byggeavhengigheter fra kontrollsiden")
SHOW_LEGEND()
@enduml
```

</details>

Agenttrafikk er avvist som standard. Listen over tillatte destinasjoner
gjelder agentenes nettverkstrafikk; imagebygging og imagehenting utføres på
den betrodde kontrollsiden. At dette repoet finnes på GitHub gir ikke
agentene automatisk GitHub-tilgang.

## C2 containere

![C2: Agentbox sine programmer, datalagre og forbindelser](diagrams/agentbox-containers.svg)

<details>
<summary>PlantUML-kilde</summary>

```plantuml
@startuml agentbox-containers
!include <C4/C4_Container>
LAYOUT_TOP_DOWN()
title Agentbox - C2 containere

Person(developer, "Utvikler", "Bruker personlig Linux-konto.")
ContainerDb_Ext(projects, "Valgte prosjektmapper", "Vertens filsystem", "Eies av utvikleren. ACL gir agentbox tilgang; mounts velges per miljø.")
System_Ext(services, "Tillatte eksterne tjenester", "Modelltjeneste, kodeverter og pakkeregistre.")
System_Ext(registry, "Image- og byggeregistre", "Tilgang fra betrodd kontrollside.")

System_Boundary(agentbox, "Agentbox") {
    Container(cli, "agentbox CLI", "Python; utviklerens UID", "Validerer miljøfiler og administrerer utviklerens ACL-endringer.")
    ContainerDb(journal, "ACL-journal", "Private JSON-filer", "/var/lib/agentbox-operator; eies av utvikleren.")
    Container(control, "Kontrollhjelper", "Python; agentbox UID", "Administrerer prosjekter, policy, miljøer og terminalsesjoner.")
    Container(watch, "Adressevakt", "Python / systemd; agentbox UID", "Stopper miljøer ved endrede vertsadresser.")
    ContainerDb(state, "Kontrolltilstand og policy", "Private filer; agentbox UID", "/var/lib/agentbox/state; miljøregister, proxyregler og logger.")
    Container(docker, "Rootless Docker-instans", "Docker Engine / RootlessKit", "Egen daemon som agentbox; administrerer containere, nettverk og images.")

    Boundary(environment, "Arbeidsmiljø - ett av flere", "Agent og proxy per miljø") {
        Container(agent, "Kodeagent og utviklingsverktøy", "Docker; UID 0 i containeren", "Upålitelig agentkode. Valgbart image; først Codex. Lukket nettverk, valgte mounts og streng seccomp.")
        Container(proxy, "Utgående proxy", "Docker / Squid; bruker proxy", "Betrodd proxy med ett grensesnitt internt og ett eksternt. Eksakte domene/port-par og fastlåste IP-adresser.")
        ContainerDb(home, "Agentens hjem og innlogging", "Containerens skrivbare lag", "/home/agent; Codex-profil. Beholdes ved stopp, slettes ved remove.")
    }
}

Rel(developer, cli, "Administrerer og åpner terminaler", "Lokale kommandoer")
Rel(developer, projects, "Redigerer", "Editor / filsystem")
Rel(cli, journal, "Registrerer og avstemmer ACL-endringer", "Filsystem")
Rel(cli, projects, "Tildeler og tilbakekaller tilgang som fileier", "POSIX ACL")
Rel(cli, control, "Sender kontrolloperasjoner", "Avgrenset sudo; JSON på stdin")
Rel(control, projects, "Reparerer ACL på filer eid av agentbox", "POSIX ACL")
Rel(control, state, "Lagrer tilstand, policy og agentutdata", "Filsystem")
Rel(watch, state, "Leser miljøer og oppdaterer status", "Filsystem og felles lås")
Rel(control, docker, "Oppretter, styrer og kjører kommandoer", "Docker CLI; fast Unix-socket")
Rel(watch, docker, "Stopper berørte containere", "Docker CLI; samme socket")
Rel(docker, agent, "Oppretter og styrer livssyklus", "Docker runtime")
Rel(docker, proxy, "Oppretter og styrer livssyklus", "Docker runtime")
Rel(docker, registry, "Henter images og bygger", "Betrodd kontrolltrafikk")
Rel(agent, projects, "Leser og endrer valgte mapper", "Eksplisitte bind mounts; rw eller ro")
Rel(agent, home, "Lagrer profil og innlogging", "Filsystem i containerlaget")
Rel(agent, proxy, "Sender utgående forespørsler", "HTTP / CONNECT via lukket nettverk")
Rel(proxy, state, "Leser kun proxyregler og fastlåste adresser", "Read-only bind mounts av to filer")
Rel(proxy, services, "Kobler til tillatt destinasjon", "HTTP / TLS-tunnel")
SHOW_LEGEND()
@enduml
```

</details>

### Grensene som betyr mest

- Den stiplede systemgrensen angir produktets omfang. Miljøgruppen samler
  agent, proxy og hjemmekatalog; nettverkstilgang følger pilene og nodenes beskrivelser.
- Utviklerkontoen og `agentbox` er separate vertsbrukere. Kontrollhjelperen
  kjører utenfor agentcontainerne; kode og private kontrollfiler monteres ikke inn.
- Én agent og én proxy vises. Hvert ekstra miljø får sitt eget par og egne
  nettverk. Docker-instansen og kontrollsiden er felles.
- Agenten har ingen forbindelse til Docker-socketen og ingen direkte
  internettrute. Pilene fra Docker viser styring, ikke en kontrollkanal agenten kan bruke.
- Proxyen monterer bare proxykonfigurasjonen skrivebeskyttet. Kontrollhjelperen
  gjør navneoppløsning og adressevalidering før de fastlåste adressene tas i bruk.
- Prosjektmapper ligger på verten og overlever fjerning av miljøet. Agentens
  hjem ligger i containerlaget; separat profilvolum er fortsatt et mulig videre valg.
- Rootless-containerne deler vertens kjerne. Ved et utbrudd med `agentbox`
  sine rettigheter gjelder brukerens samlede vertstilgang, også til andre registrerte prosjekter.
  Agentens UID 0 mappes til tjenestebrukeren på verten; proxyen bruker en egen
  containerbruker og får ikke prosjektmapper montert inn.

## Vedlikehold av diagrammene

Navngitte PlantUML-blokker i dette dokumentet er kilden til SVG- og PNG-filene
i `docs/diagrams/`. Kilden og bildene skal oppdateres sammen:

```sh
python3 scripts/render-diagrams.py
python3 scripts/render-diagrams.py --format png
```

PlantUML med lokalt C4-bibliotek og Graphviz må være installert.

```sh
python3 scripts/render-diagrams.py --jar /sti/til/plantuml-1.2026.9.jar
```

Nivåene følger C4-modellens beskrivelser av
[systemkontekst](https://c4model.com/diagrams/system-context) og
[containere](https://c4model.com/diagrams/container). Konkret oppførsel og
begrensninger beskrives i [implementasjonsvalgene](decisions-mvp.md).
