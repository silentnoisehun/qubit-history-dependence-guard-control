# Qubit History Dependence: Guard-Time Control

Repository: qubit-history-dependence-guard-control. Author: Mate Robert, ORCID https://orcid.org/0009-0003-3986-6039. DOI: pending. A GitHub repository alone has no DOI; one exists only after a tagged release is archived on Zenodo. No DOI is stated here until a real one is issued.

## English

Pre-registration and code for a single-session test of a realized history contrast D on one qubit pair (ibm_marrakesh, q21/q20).
Status: the protocol becomes locked only when the "prereg lock" commit and tag are pushed, before any hardware data; until then it is pending. Nothing here is a result.

- Question: realized rest-dependent contrast D = Lambda(0) - 0.5*(Lambda(16)+Lambda(64)) over 16 blocks, t(15) 95% CI,
  primary analysis = analyzer3.analyze_campaign on all segments pooled. No mechanism claim; population validity is not established.
- Design: 16 blocks = 16 Sampler jobs, each 2 circuits x 166 shots; each circuit has 36 segments with its own 2-bit register.
  Inter-segment guard is short (250 us) or long (1000 us), alternating pattern per block; plain measure; rep_delay/init_qubits left at the
  Runtime defaults (init_qubits True, rep_delay = backend default; the default value is recorded by hand before block 0, the runner does not log it).
- Interpretation fixed in advance: A) CI excludes 0: nonzero contrast observed in this run (no mechanism/carryover/population claim);
  B) CI includes 0 and upper bound < +0.08: no evidence of an effect as large as +0.08 in this run; C) inconclusive. Exploratory diagnostics
  (D by guard class, G0 predecessor contrast) are descriptive only.
- Stopping: usage-based only. Before each block, the sum of final usage plus remaining blocks times the largest block usage so far must be <= 304 s;
  otherwise stop and report an incomplete campaign (descriptive only). This is a forecast, not a hard guarantee of staying within 304 s. Any failed or unknown job: stop, no reruns. No outcome-based stopping, no interim CI.
- Citation: Mate Robert, ORCID 0009-0003-3986-6039. DOI pending (Zenodo archive of a tagged release required); none is claimed until issued.
- Limits: service acceptance, sub-job count and real usage unknown before block 0; carryover and drift are not separated from the effect;
  power numbers (about 85% for input D = +0.08) come from an assumed model, not hardware.
- Use: python test_v3.py (offline tests), python runner_v3.py --plan, --plan --live (read-only), --submit --live --block K (one job per call, run by the owner only),
  --analyze. See PREREG_hu.txt for the full protocol (Hungarian).

## Magyar

Elore regisztralt terv es kod egy mereshez: realizalt elozmeny-kontraszt D egy qubitparon (ibm_marrakesh, q21/q20). Allapot: a protokoll csak a "prereg lock" commit es tag pusholasa utan
lezart (hardveres adat elott); addig fuggo. Itt nincs eredmeny.

- Kerdes: realizalt rest-fuggo kontraszt D = Lambda(0) - 0,5*(Lambda(16)+Lambda(64)), 16 blokk, t(15) 95% CI, primer elemzes: analyzer3.analyze_campaign az osszes
  szegmensre poolozva. Mechanizmus-allitas nincs, populacio-ervenyesseg nincs igazolva.
- Terv: 16 blokk = 16 Sampler job, mindegyik 2 kor x 166 shot; egy kor 36 szegmens, szegmensenkent sajat 2 bites regiszterrel. A szegmensek kozti guard rovid (250 us) vagy
  hosszu (1000 us), blokkonkent valtakozo minta; plain measure; rep_delay/init_qubits a Runtime alapertelmezesen (init_qubits True, rep_delay = backend alap; az alapertek
  kezzel rogzitendo blokk 0 elott, a runner nem naploz).
- Ertelmezes elore: A) CI nem tartalmazza 0-t: nemnulla kontraszt ebben a futasban (mechanizmus/atcsuszas/populacio nincs allitva); B) CI tartalmazza 0-t es felso hatar < +0,08:
  nincs bizonyitek +0,08 nagysagu hatasra ebben a futasban; C) nem eldontheto. Feltaro diagnosztika (D guard-osztalyonkent, G0 elozmeny-kontraszt) csak leiro.
- Leallitas: csak hasznalatalapu. Minden blokk elott: vegleges usage-ok osszege + hatralevo blokkok x eddigi legnagyobb blokk-usage <= 304 s; kulonben leallas es hianyos kampany
  (csak leiro). Eredmeny alapu leallitas es kozbulso CI nincs; hibas/ismeretlen job: STOP (nincs ujrainditas).
- Hivatkozas: Mate Robert, ORCID 0009-0003-3986-6039. DOI fuggo (Zenodo-archivalt, cimkezett kiadas kell); tenyleges DOI-t addig nem allitunk.
- Korlatok: szolgaltatas-elfogadas, sub-job szam es tenyleges usage blokk 0 elott ismeretlen; atcsuszas es drift nincs elvalasztva a hatastol; a teljesitmeny-szamok (~85%, D=+0,08
  bemenettel) feltetelezett modellbol jonnek, nem hardverbol.
- Hasznalat: python test_v3.py, python runner_v3.py --plan, --plan --live (csak olvas), --submit --live --block K (hivasonkent 1 job, csak a tulajdonos futtatja), --analyze.
  A teljes protokoll: PREREG_hu.txt.
