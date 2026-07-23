# Jyotish Knowledge Boundary

This lexicon supports cautious Parāśari-style basics when the dossier is compatible.
If the report names another lineage, preserve its supplied interpretation rules and
do not silently overwrite them.

## Convention and structure

- `JYOTISH-CONVENTION-001` — Record the ayanāṃśa and whether placements are nirayana
  (sidereal) or sayana (tropical). Small convention differences can affect degrees,
  Lagna, and nakshatra boundaries.
- `JYOTISH-LAGNA-001` — Lagna is the rising point and anchors the bhāvas in many
  charts. Require reliable birth time before using it.
- `JYOTISH-LAYER-001` — Keep D1/rāśi, divisional charts, dasha, and gochara as
  distinct layers. A D9 fact is not automatically a marriage prediction.
- `JYOTISH-FUNCTION-001` — Distinguish a graha's natural significations from its
  functional role through supplied lordship and chart context. “Benefic/malefic”
  is technical, not moral.

## Graha functions

- `JYOTISH-GRAHA-SURYA` — Sūrya: agency, vitality, visibility, authority.
- `JYOTISH-GRAHA-CHANDRA` — Chandra: mind, habit, receptivity, care, fluctuation.
- `JYOTISH-GRAHA-MANGALA` — Maṅgala: force, courage, severing, contest, action.
- `JYOTISH-GRAHA-BUDHA` — Budha: discrimination, speech, calculation, exchange.
- `JYOTISH-GRAHA-GURU` — Guru/Bṛhaspati: counsel, expansion, meaning, teaching.
- `JYOTISH-GRAHA-SHUKRA` — Śukra: relationship, pleasure, art, agreement, value.
- `JYOTISH-GRAHA-SHANI` — Śani: duty, delay, endurance, scarcity, structure.
- `JYOTISH-GRAHA-RAHU` — Rāhu: amplification, appetite, anomaly, foreignness.
- `JYOTISH-GRAHA-KETU` — Ketu: separation, compression, inwardness, discontinuity.

## Bhāva and modifier rules

- `JYOTISH-BHAVA-001` — 1 self/body; 2 speech/family/resources; 3 effort/siblings;
  4 home/mother/contentment; 5 learning/children/creation; 6 service/conflict/debt;
  7 partnership/public exchange; 8 vulnerability/joint matters/transformation;
  9 dharma/teachers/long journeys; 10 action/status/work; 11 gains/networks;
  12 expenditure/retreat/foreign or secluded settings.
- `JYOTISH-DIGNITY-001` — Use exaltation, debilitation, own sign, mūlatrikoṇa,
  combustion, retrogression, or avasthā only when explicitly supplied. No condition
  acts alone.
- `JYOTISH-DRISHTI-001` — Graha drishti and rāśi drishti are different rule systems.
  Use only the aspect type named in the dossier.
- `JYOTISH-NAKSHATRA-001` — A supplied nakshatra and pada may qualify a graha's
  manner or motivation. Never infer a nakshatra from a rounded sign placement.
- `JYOTISH-YOGA-001` — Interpret a yoga only if the source names it and supplies its
  component facts. Treat it as a configuration, not an event guarantee.
- `JYOTISH-DASHA-001` — A dasha interpretation requires the named dasha system,
  active mahādasha/antardasha, and date range. Frame timing as emphasis and activation
  of supplied natal factors.
- `JYOTISH-TRANSIT-001` — Use gochara only with the transiting graha, reference point,
  and time window explicitly present.

## Source notes

- P. V. R. Narasimha Rao, *Vedic Astrology: An Integrated Approach*, used to
  cross-check basic terminology, grahas, nirayana/sayana distinction, divisional
  charts, and the distinction between graha and rāśi drishti:
  https://www.vedicastrologer.org/articles/vedic_astro_textbook.pdf
- Drik Panchang Kundali documentation, used to confirm that reports expose multiple
  ayanāṃśas, D1/D9 layers, nakshatras, and Vimshottari dasha:
  https://www.drikpanchang.com/jyotisha/kundali/kundali.html
- Jagannatha Hora feature documentation, used to verify that house and calculation
  schemes are configurable:
  https://www.vedicastrologer.org/jh/features.htm
