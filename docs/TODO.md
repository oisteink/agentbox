# Planlagt arbeid

## Neste versjon: QA og revisjon av tester

Status: planlagt, ikke startet. Gjennomføres på en egen gren fra `main`,
eksempelvis `qa/test-review`, adskilt fra proxyutvidelsen.

Testene har vokst gjennom flere leveranser. Gå gjennom hva de faktisk
bekrefter, hvor de overlapper og hvilke krav som fortsatt mangler bevis.
Oversikt over sikkerhetsmodellen skal styre testarbeidet.

- Koble sikkerhetskrav og sentrale brukerflyter til konkrete tester.
- Finn tester som kan passere av feil grunn, særlig negative nettverksprøver
  uten fungerende kontrolltjeneste og mottakerobservasjon.
- Vurder overlapp, overflødige mocks og tester som bare gjentar implementasjonen.
  Forenkle uten å miste relevant dekning.
- Kontroller fixtures, opprydding, reproduksjon og skillet mellom lokal test,
  VM-prøve og manuell verifikasjon. Avinstallasjonsprøven skal fortsatt kjøres sist.
- Oppdater teststruktur og dokumentasjon med observerte resultater og åpne hull.

Ferdig når testenes formål og kravdekning er dokumentert, funn er håndtert
eller eksplisitt videreført, og den reviderte pakken er kjørt i relevante miljøer.
Flere tester eller en høyere testprosent er ikke et mål i seg selv.
