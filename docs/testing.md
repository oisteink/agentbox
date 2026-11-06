# Tester i Agentbox

Testene skal vise at utvikleren kan bruke Agentbox, og at agenten holder seg
innenfor de beskrevne tillitsgrensene. [Produktspesifikasjonen](specification.md)
er kontrakten. [Teststatus](test-results.md) sier hva som faktisk er prøvd og
på hvilken plattform.

## Arbeidsmåte ved endringer

Start med brukerhandlingen eller sikkerhetskravet som endres. Beskriv
forutsetning, handling og observerbart resultat før testen skrives. Ved
feilrettinger skal testen feile på den opprinnelige feilen og bestå etter
rettingen. Undersøk også hvorfor eksisterende tester ikke oppdaget feilen.

Velg det minste testnivået som kan gi riktig bevis:

- Rene parser-, ACL- og policyregler prøves lokalt med konkrete innganger og
  forventede resultater. Tabeller passer til grenseverdier og ugyldige varianter.
- Prosess-, terminal- og filsystemoppførsel prøves med ekte lokale ressurser
  når det er mulig. Erstatt eksterne operasjoner ved grensen; ikke simuler hele Docker.
- Installerte brukerflyter prøves gjennom CLI, sudo-hjelper og faktiske
  rootless-containere i disponibel VM. En simulert RPC er ikke dette beviset.
- Proxyens HTTP/TLS-regler prøves med kontrollerte klienter og mottakere.
  VM-prøven undersøker også faktiske nettverk og produksjonsimage.

En negativ test skal utløse riktig avslag. En vilkårlig feilstatus er sjelden
tilstrekkelig: kontroller feilkategori eller errno og relevant ettertilstand.
En nettverksprøve trenger en fungerende kontrolltjeneste før blokkering kan
godtas. Skal HTTP aldri nå frem, kontroller også mottakerens observasjoner.
Ved forventet transportavbrudd kontrolleres tjenesten igjen etterpå.

Bevaring av containerlaget krever en markør utenfor mountene og
kontroll av samme agentcontainer. En fil i et mount alene viser bare at mountet
beholder innholdet. Terminalinnlesing må gi et svar fra containerprosessen
som ikke kan forveksles med terminalekko.

Hvert installerte scenario har eget oppsett og egen opprydding. Registrer
ressursnavn før opprettelse, slik at delvis opprettede ressurser også ryddes.
Forsøk alle oppryddingssteg og rapporter feil. Ikke slett feilsøkingsgrunnlaget
eller rapporter bestått hvis opprydding feiler. Tester som endrer labens felles
nettverk, daemon eller installasjon kjøres sekvensielt.
Livssyklusfixturen undersøker både miljøregisteret og faktiske containere/nettverk
med miljøets etikett etter fjerning; en vellykket CLI-respons alene er utilstrekkelig.

## Kontroller før merge

En agentsandkasse kan skjule `/dev/kvm` selv om verten har KVM. Kontroller
tilgangen på verten før laben regnes som utilgjengelig.

Kjør `scripts/check.sh` for låste Python-avhengigheter, pytest, Ruff,
Bash-syntaks, Go race/vet, govulncheck og gofmt. Dette krever Python 3.12+,
uv, Go og tilgang til toolchain 1.27.3 og sårbarhetsdatabasen.

Endringer i CLI, kontrollkode, runtime, ACL, installasjon, images eller
nettverk krever også `scripts/lab/check.sh` inne i laben. Dokumentasjonsendringer
og rene parserendringer vurderes etter berørt krav. En full leveranseprøve
bruker `scripts/lab/check.sh --uninstall`; avinstallasjon skjer sist og sletter
installasjonen. Kommandoer for oppsett står i [teststatus](test-results.md#reproduser-laben).

Labinngangen krever vertsnavnet `agentbox-lab` og operatøren `developer` før
mutasjon. Den installerer kildekoden på nytt, bygger images og sammenligner
installerte kildefiler med kilden. Et privat resultatutdrag registrerer
kildenes hash, image-ID-er, plattform, Python og pytest. Labens separate venv
bruker versjoner og pakkehasher fra `uv.lock`. Hoppede eller ingen
livssyklustester gjør kjøringen mislykket. Proxyprøven kjøres også om et
livssyklusscenario feiler; samlet resultat forblir mislykket.

Oppdater kravmatrisen ved endrede kontrakter. Teststatus skal oppgi resultat, dato, plattform, prøvenes omfang og hull. Nytt testantall eller høyere
dekningsprosent er ikke et akseptansekriterium.

## Krav og bevis

Testnavnene nedenfor viser kjørbare observasjoner. De innebærer ikke at hele
kravet er uttømmende verifisert. Installerte scenarier ligger i
`tests/integration/test_lifecycle.py`, `test_temporary_run.py`,
`test_installation.py`, `test_json.py`, `test_mounts.py` og `test_uninstall.py` og bruker installert CLI.

| Krav | Konkret prøve | Avgrensning |
| --- | --- | --- |
| A1: riktig daemon | `test_runtime`: rootful, endret ID, cgroupstøtte og renset miljø; labens `doctor` | Socketmodus, versjonsgrenser og fiendtlig Docker-context er ikke alle prøvd på nytt i lab |
| A2: samtidige miljøer | `test_two_images_and_independent_environments` | To miljøer; ingen stor lastprøve |
| A3: valgte mapper | `test_mount_visibility_and_readonly` med fungerende valgt mount og skjult søskenmappe | Bredere mount-/symlinkkombinasjoner mangler |
| A4: samarbeid om filer | `test_mount_file_operations_and_remove_preserve_code`, `test_acl_repair_and_revocation_leave_other_mount_working`; lokale ACL-regler | Ikke alle kombinasjoner av eierskap, filmoduser og samtidige redigeringer |
| A5: read-only og bevart kode | `test_mount_visibility_and_readonly` krever EROFS; filoperasjonstesten leser etter remove; uninstall starter med privat nestet mount | Ikke alle mountkombinasjoner |
| A6: tillatt/avvist HTTP og HTTPS | `credential_proxy.py`: positiv kontroll, eksakt domene/port, mottakerobservasjon; `TestInterceptPolicy` | Go-testens dialer omdirigeres lokalt; VM kreves for offentlig pinning |
| A7: direkte nettverk | `test_environment_network_isolation` med kontroll mot faktisk mål-IP før/etter; proxyprøvens direkte TCP-avslag | Kontrollert UDP, ekstern DNS, vert/LAN og aktiv IPv6 krever egne oppdaterte prøver |
| A8: DNS og private adresser | `test_policy`, `TestPolicyRejectsUnsafeInputs`, proxyprøvens pinning og endring til loopback | Ingen oppdatert mottakerprøve av Docker-resolverens eksterne videresending |
| A9: ingen fallback | Proxyprøvens stopp, avvist apply og tom/ikke-tom overgang; `test_proxy_credentials` | Ikke alle crash-/readinessfeil er injisert |
| A10: agentens begrensninger | `test_socket_capability_and_cgroup_enforcement`: AF_UNIX gir EPERM, Docker-socket mangler, ip link avvises; asyncio fungerer | Alternative socketsyscalls, mount-forsøk og skriving til alle kontrollfiler trenger egne prøver |
| A11: to images | `test_two_images_and_independent_environments` med utviklingsimage og uavhengig smoke-image | Andre agentmaler har bare bygg-/versjonsprøve; arm64 er ikke prøvd |
| Lokale imageoppskrifter | `test_images`: filer, binær protokoll, sikker utpakking, eierskap og eksakt brukssjekk; `test_local_image_build_context_and_use_guard`: COPY/ignore og ombygging | Installert på Ubuntu amd64; andre plattformer er ikke prøvd |
| A12: ressurser | `test_socket_capability_and_cgroup_enforcement` leser CPU/minne/PID og fyller PID-grensen; lokal daemonprøve av manglende støtte | Ingen ny CPU-belastnings- eller OOM-prøve |
| A13: tilbakekalling | `test_acl_repair_and_revocation_leave_other_mount_working`: varsling under read-only bruk, EACCES som tjenestebruker og annet mount fortsetter; ACL-unitprøver | Konkurrerende manuelle ACL-endringer mangler |
| Installasjon | `test_install` validerer operatørvalg; `test_proxy_image_installation_and_build_failure` prøver proxybygg, gjenbruk og feilstatus; laben sammenligner installerte filer | Minste Debian er ikke fastsatt |
| Shell, exec og terminal | `test_exec_exit_status_and_configured_shell`, `test_terminal_reads_input_and_preserves_size`, lokal PTY-prøve | Dynamisk størrelsesendring og signaler i vedvarende shell/exec trenger egne prøver; midlertidig run/shell har Ctrl-C-prøver |
| Stopp/start og endret profil | `test_stop_start_preserves_container_and_home`, `test_changed_profile_waits_for_restart_and_recreates_container` | Home-markør og samme container-ID; full innlogging er ikke utført her |
| Ikke-persistent miljø | `test_temporary_run.py`: start/shell, rent hjem ved neste start, ny ID, stop, mount-bevaring og konkurrerende shell; `test_run.py`: reservasjon, signalgap og identitetsbinding | Hardt avbrudd krever eksplisitt remove |
| Midlertidig kjøring | `test_temporary_run.py`: exitkode, terminal, Ctrl-C, ressursfjerning og mount-bevaring; `test_run.py`: feilbaner og identitetsbinding | SIGKILL/vertskrasj krever eksplisitt opprydding |
| Eksempelmaler | `test_example_agent_version_in_isolation`, `test_agent_examples_match_cli_templates_and_archive` | Bygg og versjonskommando er prøvd; ikke TUI, innlogging eller modelltrafikk |
| Daemonrestart | `test_daemon_restart_preserves_home` | Ikke vertsreboot eller avbrudd ved hvert oppstartssteg |
| Tokenlivssyklus | `test_proxy_credentials`, Go-testene og `credential_proxy.py` med syntetiske tokens | Nye prøver bruker ingen ekte nøkler eller modellkall |
| Tilstand og logger | `test_state`, kontrollinngangens feilprøver, exec-testens logginnhold og proxyprøvens loggkontroll | Samtidige låser, loggrotasjon og private filmoduser mangler full labdekning |
| Avinstallasjon | `test_full_uninstall_keeps_mounts_and_returns_ownership`, `test_uninstall` | Egen opt-in, rootful kontrollinstans og sist i labløpet |

## Testenes ansvar

| Filer | Formål og avhengigheter |
| --- | --- |
| `tests/unit/test_config.py`, `test_policy.py` | YAML-/skjemagrenser, kortnavn, DNS-validering og generert domene/port-policy; DNS-svar er kontrollerte |
| `test_proxy_credentials.py`, `test_credentials.py` | Tokenreferanser, alias, plassholdere, hemmelighetsfrie argumenter/feil og avslag ved overganger; enkelte eksterne kontrolloperasjoner erstattes |
| `test_cli.py`, `test_control_entry.py`, `test_output_process.py` | Utvalgte CLI-forespørsler, identitet før dispatch og avvisning av feil input uten ekko av hemmeligheter |
| `test_runtime.py` | Daemonkrav og renset miljø med simulerte Docker-svar; ekte PTY/prosess for utdata og initial størrelse |
| `test_images.py` | Ekte lokale oppskrifter, editorprosesser, tar og utpakking; binær kontrollprotokoll og avslag før Docker-mutasjon |
| `test_mounts.py`, `test_uninstall.py` | ACL-transformasjoner, lenker, identitet og filsystemopprydding; smale mocks for eksterne ACL-operasjoner |
| `test_state.py` | Reell atomisk lagring og avbrutt transaksjon i midlertidig mappe |
| `test_install.py`, `test_completion.py` | Operatørvalg før privilegier, ekte Bash-completion og kontrollerte navneoppslag |
| `proxy/proxy_test.go`, `proxy/security_test.go` | Ekte HTTP/TLS, H1/H2, auth-/destinasjonsregler, mottakerobservasjon og positive kontrollrequests |
| `tests/integration/conftest.py`, `test_lifecycle.py` | Funksjonsavgrenset ressursoppsett og selvstendige scenarier mot installert kode |
| `tests/unit/test_run.py`, `tests/integration/test_temporary_run.py` | Midlertidig kjøring, signaler, opprydding og feilstatus |
| `tests/integration/test_installation.py` | Faktisk installasjon med eksisterende/manglende proxyimage og ugyldig Dockerfile; gjenoppretter installasjonen etter prøven |
| `tests/integration/test_uninstall.py` | Destruktiv installert prøve; eierbytte, ACL, symlinker, nestet mount og bevart annen daemon |
| `scripts/lab/credential_proxy.py`, `fixture.py` | Samlet proxy-/tokenlivssyklus med syntetisk upstream i egen nettverksnamespace; fixture er bare labserver |
| `scripts/check.sh`, `scripts/lab/check.sh` | Lokale kontroller og installert akseptanse; resultatfilene er disponible |
| `scripts/lab/vm.sh`, `bootstrap.sh`, `build-images.sh` | Disponibel VM, forutsetninger og fixture-images; er oppsett, ikke selvstendige bevis |

Parser- og labprøver overlapper bevisst: de undersøker validering og faktisk
håndheving på hver sin side av prosessgrensene. Testene skal ikke dupliseres
med nye mocks av de samme interne kallene.

## Åpne verifikasjonshull

Disse hullene skal vurderes ved endringer i berørt område og før utvidet
plattformstøtte. De er ikke beståtte prøver:

1. Prioritet høy: Debian som vertsplattform. Velg en konkret kandidatversjon,
   kjør installasjon, fulle labscenarier og avinstallasjon, og fastsett deretter
   minste støttede versjon. Et Debian-basert proxyimage beviser ikke vertsbruk.
2. Prioritet høy ved nettverksoppgradering: kontrollert UDP/DNS-mottaker og
   positiv klient utenfor agentnettet. Prøv direkte UDP, vert/LAN, Docker-
   resolver og tilgang uten proxyvariabler. Registrer mottakerhendelser;
   en DNS-feil alene er utilstrekkelig.
3. Prioritet høy ved seccomp-endring: mountet kontrollsocket som virker med
   standardprofilen, avslag med installert profil, alternative socket-/io_uring-
   syscalls og tilkoblingsforsøk med socketpair. Behold fungerende stream-IPC.
4. Prioritet middels: avbrudd mellom hver varig oppstartsoperasjon, samtidig
   start/stop/revoke, manuelle ACL-endringer og gjenoppretting uten fremmede
   ressursendringer. Bruk eksplisitte feilpunkter og ettertilstand.
5. Prioritet middels: vertsreboot, signaler i vedvarende shell/exec og dynamisk terminalstørrelse,
   arbeidskatalog som mangler/erstattes, privat loggmodus/rotasjon og CPU/OOM.

Maskinprotokollen prøves med reelle prosesser for store toveis strømmer,
tidlig stdin-stenging, ugyldig/delt UTF-8, parserfeil og avbrudd mens input
venter. `test_json.py` prøver installert CLI gjennom sudo: mennesketabell,
JSON-feil, adskilte utstrømmer, stdin, logger og identitetsbundet opprydding
etter Ctrl-C. En JSON-exitkode 0 er utilstrekkelig; sluttresultatet må finnes
og undersøkes.

Mount-prøvene dekker separate lagringskilder: profilvolum gjennom run,
containerfjerning og imagebytte; eksplisitt HOME i ikke-persistent miljø;
ro/rw; revoke med aktiv bruker/åpent håndtak; fix uten reaktivering; navngitt
samtykke for aktive/stoppede volumbrukere; katalogdata/operatørtilgang etter
remove; manglende/fremmed volum; og ufullstendig cleanup med retry. Lokale
feilprøver dekker samtykke ved endret kilde/ressurser og avbrudd mellom ACL-pass,
før forget og etter volumsletting. Vanlig remove prøves uten root/chown.

Imageoppskrifter prøves med lokal default/prioritet, hel kontekstkopi, edit-
endringer og inputdigest uten tidsstøy. Brukssjekk må dekke tagflytting og
stoppede containere. Preflight-feil skal beholde gammelt stoppet lag.
Run-retry må bevare stor pipet input, aldri skje etter input_ready/Ctrl-C,
og fortsatt gi ett offentlig sluttresultat. Installert exec prøves med
CONFIG, automatisk bygg/start, valgt ID og proxy som forblir stoppet.
