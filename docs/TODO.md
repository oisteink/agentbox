# Videre arbeid

Vedtatte CLI-krav og oppfølgingsissues står i
[planlagt CLI og livssyklus](features/session-lifecycle/spec.md#oppfølging).
Disse er ikke implementert.

Gjeldende testansvar og kravdekning står i [teststrategien](testing.md).
De viktigste gjenstående verifikasjonene er:

- Fastsett minste Debian-versjon gjennom installasjon, akseptanse og
  avinstallasjon på en konkret Debian-vert.
- Oppdater kontrollert UDP/DNS- og vert/LAN-prøve før nettverksplattformen
  oppgraderes. Gjenta alternative socketsyscalls ved endring av seccomp.
- Prøv avbrudd under oppstart, samtidige kontrolloperasjoner og ACL-konflikter.
- Prøv signaler i vedvarende shell/exec, dynamisk terminalstørrelse, privat
  loggmodus/rotasjon, vertsreboot og faktisk CPU-/minnehåndheving.

Konsekvens og nødvendig prøve for hvert hull står under
[åpne verifikasjonshull](testing.md#åpne-verifikasjonshull).
