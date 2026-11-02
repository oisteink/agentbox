# Videre arbeid

Gjeldende testansvar og kravdekning står i [teststrategien](testing.md).
De viktigste gjenstående verifikasjonene er:

- Fastsett minste Debian-versjon gjennom installasjon, akseptanse og
  avinstallasjon på en konkret Debian-vert.
- Oppdater kontrollert UDP/DNS- og vert/LAN-prøve før nettverksplattformen
  oppgraderes. Gjenta alternative socketsyscalls ved endring av seccomp.
- Prøv avbrudd under oppstart, samtidige kontrolloperasjoner og ACL-konflikter.
- Utvid terminalprøver med signaler og dynamisk størrelse, og prøv privat
  loggmodus/rotasjon, vertsreboot og faktisk CPU-/minnehåndheving.

Konsekvens og nødvendig prøve for hvert hull står under
[åpne verifikasjonshull](testing.md#åpne-verifikasjonshull).
