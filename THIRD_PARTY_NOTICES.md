# Third-party computation and data

Castle uses these libraries locally; it is not affiliated with or endorsed by their authors.
Exact JavaScript versions and transitive dependency integrity hashes are pinned in `engines/package-lock.json`.
Unmodified upstream license files remain included in installed packages and the Docker image.

| Component | Source | License / use |
| --- | --- | --- |
| @openfate/bazi-engine 1.1.3 | https://github.com/openfate-ai/bazi-engine | MIT; Four Pillars / Ten Gods; Castle selects and adapts outputs |
| @openfate/true-solar-time (transitive) | https://github.com/openfate-ai/true-solar-time | MIT; solar clock correction, via BaZi engine |
| lunar-javascript (transitive) | https://github.com/6tail/lunar-javascript | MIT; Chinese calendar / solar terms |
| iztro 2.6.1 | https://github.com/SylarLong/iztro | MIT; Ziwei chart calculation |
| astronomy-engine 2.1.19 | https://github.com/cosinekitty/astronomy | MIT; astronomical positions and coordinate transforms |
| hd-chart-engine 0.1.1 | https://github.com/domalhambra/hd-chart-engine | MIT default Astronomy Engine adapter; solar-arc solver, gate/line mapping, approximate true lunar node. Optional GPL `ephemeris` / `moshier` path is not installed or used. |
| natalengine 1.6.0 | https://github.com/Unforced-Dev/natalengine | MIT; HD gate/channel tables, rashi/nakshatra tables, approximate Lahiri function, Vimshottari lord/year constants. Not its full chart calculators, interpretation text, MCP server or renderers. |
| geonamescache 3.0.1 | https://github.com/yaph/geonamescache | MIT for library code |
| GeoNames city data | https://www.geonames.org/export/ | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); Castle filters city names and displays city center coordinates/timezones. No endorsement. |
| tzdata 2025.2 | https://github.com/python/tzdata | Apache-2.0 package; underlying IANA timezone data is public domain |

The computation adapter, local search UI, normalized facts, and interpretation workflow are Castle code, not upstream reports. Symbolic interpretations must not be mistaken for scientifically established personality or life predictions.

Castle's numerology and Dreamspell calculations are local implementations of the disclosed conventions, not downloaded reports or calls to third-party chart services. Algorithm references (not endorsements):

- Numerology.com: [Life Path reduction](https://www.numerology.com/articles/your-numerology-chart/life-path-number-meanings/), [name numerology](https://www.numerology.com/articles/your-numerology-chart/name-numerology/). Castle explicitly chooses whole-name summation, A–Z only, optional Y-as-vowel, and master numbers 11/22/33.
- Foundation for the Law of Time: [year/month decoding table](https://www.lawoftime.org/pdfs/OvertoneMoon.pdf), [leap-day decoding guidance](https://lawoftime.org/decode/). Dreamspell is a modern system, not the historical Maya calendar.

See `docs/CALCULATION-ENGINES.md` for limitations and regression coverage. No compatibility with other conventions is implied.
