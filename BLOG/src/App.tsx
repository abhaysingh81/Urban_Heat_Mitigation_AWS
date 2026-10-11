import { useState } from 'react';
import { Masthead } from './components/Masthead';
import { Hero } from './components/Hero';
import { CityExplorer } from './components/CityExplorer';
import { ModelFigure, ErrorTable, ShapFigure } from './components/ModelFigure';
import { WardFigure } from './components/WardFigure';
import { PlanFigure, planAt } from './components/PlanFigure';
import { BriefFigure } from './components/BriefFigure';
import { AwsFigure } from './components/AwsFigure';
import { CITY_IDS, CITY_NAME, model, plans, sites, totals, wards, type CityId } from './lib/data';
import { fmt } from './lib/heat';
import { AI_TOOLS, AWS_STATUS, LOOP, REFERENCES, REPO_URL, SOURCES } from './content';

// ---- figures quoted in the prose, all derived from exported data ----
const range = (xs: number[]) => [Math.min(...xs), Math.max(...xs)] as const;
const blockR = range(CITY_IDS.map((c) => model.block_cv[c].pearson_r));
const biasR = range(CITY_IDS.map((c) => model.loco[c].bias));
const baseR = range(CITY_IDS.map((c) => model.baseline_r[c]));
const delhiBudget = sites.new_delhi.budget_lakh;
const delhiEff = planAt('new_delhi', delhiBudget, 0);
const delhiEq = planAt('new_delhi', delhiBudget, 1);
const allPlanTypes = new Set(CITY_IDS.flatMap((c) => plans[c].flatMap((p) => p.by_type.map((t) => t.label))));
const onlyShade = [...allPlanTypes].every((l) => /shade|cooling centre/i.test(l));
const delhiWards = wards.new_delhi;

function Chapter({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="chapter" aria-labelledby={`${id}-h`}>
      <div className="prose-col">
        <h2 id={`${id}-h`} className="chapter-title">{title}</h2>
      </div>
      {children}
    </section>
  );
}

export default function App() {
  const [city, setCity] = useState<CityId>('new_delhi');

  return (
    <>
      <a href="#problem" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 ui" style={{ zIndex: 50 }}>
        Skip to the article
      </a>
      <Masthead />
      <Hero />

      <main>
        {/* ------------------------------------------------------------ */}
        <Chapter id="problem" title="A heat map is not a decision">
          <div className="prose-col">
            <p className="lede">
              Picture a municipal officer in May with a fixed budget for heat. Trees, cool roofs, shade at bus stops, a cooling centre: which, where, and for whom? And how do they explain the choice to the people in the next ward who got nothing?
            </p>
            <p>
              The stakes are not abstract. The World Health Organization estimates <strong>about 489,000 heat-related deaths a year</strong> worldwide between 2000 and 2019, 45% of them in Asia. The 2024 Lancet Countdown found heat-related deaths among people over 65 were <strong>167% higher in 2023</strong> than in the 1990s.
            </p>
            <p>
              Indian cities are not short of plans. In 2023 the Centre for Policy Research reviewed <strong>37 heat action plans across 18 states</strong> and found the same gaps again and again: weak local data, little targeting of vulnerable people, unclear funding and almost no transparency about why money went where it did.
            </p>
            <p>
              A satellite heat map answers “where is the ground hot?”. The officer’s questions are different: who lives there, how exposed they are, what each rupee buys, and how sure we are. HeatRelief is decision support for that gap. It will not stop a heatwave, and it does not pretend to.
            </p>
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="built" title="What we built">
          <div className="prose-col">
            <p>
              HeatRelief is one loop with six steps. Each step’s output is something an official can inspect, question and overrule.
            </p>
          </div>
          <div className="wide-col">
            <ol className="list-none m-0 p-0 my-10 grid gap-px sm:grid-cols-2 lg:grid-cols-3" style={{ background: 'var(--rule)', border: '1px solid var(--rule)' }}>
              {LOOP.map((s, i) => (
                <li key={s.verb} className="p-5 sm:p-6" style={{ background: 'var(--bg)' }}>
                  <div className="flex items-baseline gap-3 mb-2">
                    <span className="ui num font-extrabold text-[2rem] leading-none" style={{ color: 'var(--heat)', fontStretch: '75%' }}>{i + 1}</span>
                    <span className="font-bold text-[1.2rem]" style={{ fontFamily: 'var(--font-display)', fontStretch: '85%' }}>{s.verb}</span>
                  </div>
                  <p className="m-0 ui text-[0.95rem] leading-snug" style={{ color: 'var(--ink-2)' }}>{s.text}</p>
                </li>
              ))}
            </ol>
          </div>
          <div className="prose-col">
            <p>
              <strong>What existed before the hackathon, and what we built during it.</strong> We started from an earlier project of ours: a heat-map dashboard with a SHAP view and a two-option scenario builder for 20 Indian cities, running on a <em>synthetic</em> temperature generator. During the event we replaced the synthetic core with real satellite data for four cities, trained and validated a new model, and built everything after the map: the risk ranking, the budget optimizer, the AI brief, the morning alert and the AWS stack.
            </p>
            <p>
              The other 16 cities still run on synthetic data. They stay in the product as labelled previews, so you can see the workflow, but no number from them appears in this post.
            </p>
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="ground" title="Reading the ground from orbit">
          <div className="prose-col">
            <p>
              Everything starts on a common grid: <strong>500-metre cells</strong>, the same fishnet for every source. Seven open datasets go into it.
            </p>
          </div>
          <div className="prose-col">
            <div className="overflow-x-auto my-8">
              <table className="data-table min-w-[36rem]">
                <thead>
                  <tr><th>Source</th><th>What we take from it</th><th>Resolution</th><th>Licence</th></tr>
                </thead>
                <tbody>
                  {SOURCES.map((s) => (
                    <tr key={s.name}>
                      <td className="font-semibold">{s.name}</td>
                      <td style={{ color: 'var(--ink-2)' }}>{s.what}</td>
                      <td className="whitespace-nowrap" style={{ color: 'var(--ink-2)' }}>{s.res}</td>
                      <td className="whitespace-nowrap" style={{ color: 'var(--muted)' }}>{s.licence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              The target is the Landsat surface temperature: for each city, the median of at least six cloud-free Landsat 8/9 scenes from April to June across 2024–2026. One hot afternoon can be a fluke. A three-season median shows which blocks are hot every year.
            </p>
          </div>

          <CityExplorer city={city} onCity={setCity} />

          <div className="prose-col">
            <div className="aside-note">
              <b>Surface temperature is not heat stress.</b> Landsat measures how hot roofs, roads and fields are. It does not measure the air people breathe, humidity or how a body copes. We use it to find where the built environment traps heat, and we say “surface” every time we quote it.
            </div>
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="model" title="Testing on a city the model never saw">
          <div className="prose-col">
            <p>
              Landsat only passes every few days and clouds hide whole districts, so we need a model to fill gaps and, more importantly, to estimate what changes when a block gets trees or shade. We use XGBoost with {model.n_features} features (land cover, the satellite indices, terrain, population, neighbourhood context and scene-day weather), plus two quantile models for a q10–q90 uncertainty band.
            </p>
            <p>
              The trap with map data is that neighbouring cells look alike. Split cells at random and the test set is full of near-copies of the training set, so the score flatters you. Even holding out 5 km blocks inside each city gave r = {blockR[0].toFixed(2)}–{blockR[1].toFixed(2)}. That would look great in a pitch, but the model had still seen the city it was tested on.
            </p>
            <p>
              The honest test: <strong>train on three cities, score on the fourth</strong>, rotate.
            </p>
          </div>
          <div className="prose-col">
            <ModelFigure />
          </div>
          <div className="prose-col">
            <p>
              On cities it never saw, the model keeps the spatial pattern: r = {totals.minR.toFixed(2)}–{totals.maxR.toFixed(2)}. The obvious simple model, a straight line through greenness and concrete, is <em>negative</em> everywhere ({fmt.r(baseR[0])} to {fmt.r(baseR[1])}). The relationship between green cover and heat is real but not linear, and it changes from city to city.
            </p>
            <p>
              What does <em>not</em> transfer is the absolute level. Each held-out city carries an offset of {fmt.signed(biasR[0])} to {fmt.signed(biasR[1])} °C:
            </p>
            <div className="my-8"><ErrorTable /></div>
            <p>
              So we changed the design around the weakness. Heat tiers and risk use the <strong>observed</strong> Landsat composite wherever it exists. The model is used for what it is good at: filling cells the satellite missed, and estimating the <em>difference</em> an intervention makes, where a city-wide offset cancels out.
            </p>
            <p className="subhead" role="heading" aria-level={3}>What the model leans on</p>
            <ShapFigure />
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="wards" title="From hot pixels to a ranked list">
          <div className="prose-col">
            <p>
              A hot cell with nobody in it is not an emergency. The ranking combines three things per zone, each as a percentile against the rest of the city, and multiplies them:
            </p>
            <p className="ui my-8 text-center" style={{ fontSize: 'clamp(1.05rem, 0.9rem + 0.6vw, 1.35rem)', color: 'var(--ink)' }}>
              <span style={{ color: 'var(--heat-ink)', fontWeight: 700 }}>hazard</span>
              {' × '}
              <span style={{ fontWeight: 700 }}>exposure</span>
              {' × '}
              <span style={{ color: 'var(--cool-ink)', fontWeight: 700 }}>vulnerability</span>
            </p>
            <p>
              <strong>Hazard</strong> is the zone’s mean and 90th-percentile surface temperature. <strong>Exposure</strong> is how many people live there. <strong>Vulnerability</strong> is a crowding and green-deficit proxy: population density, lack of vegetation and building density. Because it is a product, a zone has to score on all three to reach the top. Every component is returned with the score, so “why is my ward ranked third?” has an answer.
            </p>
          </div>
          <div className="prose-col">
            <WardFigure city={city} onCity={setCity} />
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="plans" title={`Same ${fmt.crore(delhiBudget)}, two plans`}>
          <div className="prose-col">
            <p>
              The optimizer takes a budget and five possible actions: trees, cool roofs, shade structures, cool pavements and cooling centres. Each action has a published low/mid/high cooling range, scaled by how suitable a cell is (space to plant, roof share, foot traffic) and, for trees, by survival rate and years to maturity. It picks actions greedily by benefit per rupee and never exceeds the budget.
            </p>
            <p>
              The interesting part is one dial, <strong>λ</strong>. At λ = 0 it buys the most cooling per rupee. At λ = 1 it weights each degree by how many vulnerable people feel it. These are different goals, and the plan should say out loud which one it is serving.
            </p>
          </div>

          <PlanFigure city={city} onCity={setCity} />

          <div className="prose-col">
            <p>
              In Delhi, with the same {fmt.crore(delhiBudget)} and the same {delhiEff.n_actions} sites, the equity plan reaches <strong>{fmt.lakhPeople(delhiEq.people_protected)}</strong> people against <strong>{fmt.lakhPeople(delhiEff.people_protected)}</strong>, and the cost per person drops from ₹{fmt.int(delhiEff.cost_per_person_inr)} to ₹{fmt.int(delhiEq.cost_per_person_inr)}. The money doesn’t change. Where it goes does.
            </p>
            {onlyShade && (
              <div className="aside-note">
                <b>Look at what it buys.</b> In every plan we exported, the optimizer picks only shade structures and cooling centres, never trees or cool roofs. That is not a finding about trees. Our cost and cooling figures are planning placeholders, and with these placeholders shade wins on cooling per rupee. The mix of actions is only as good as those inputs, which is why replacing them with local quotes is first on our list.
              </div>
            )}
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="briefs" title="A brief an officer can read, numbers the AI can’t invent">
          <div className="prose-col">
            <p>
              The last step is words. A ward officer needs a page, not a dashboard, and many of the people affected read Hindi first. The AI Heat Officer is a <strong>Strands agent</strong> (AWS’s open-source agent SDK) on <strong>Amazon Bedrock</strong> with five tools: ward risk, ward plan, nearby cooling spots, forecast and heat-health guidance.
            </p>
            <p>
              The rule is strict. Code computes every number; the language model only phrases it. After the model writes, a checker pulls out every number in the brief, English or Devanagari digits, and confirms each one appears in what the tools returned.
            </p>
          </div>
          <div className="wide-col">
            <BriefFigure />
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="aws" title="Where AWS fits">
          <div className="prose-col">
            <p>
              The product has two rhythms. Every morning at 06:00 IST, a scheduled job re-ranks wards against the day’s forecast and decides whether to alert. During the day, officers ask for plans and briefs on demand. Both run on serverless AWS, so a city pays for what it uses and nothing runs between requests.
            </p>
          </div>
          <div className="wide-col">
            <AwsFigure />
          </div>
          <div className="prose-col">
            <p>
              The choices we would defend: <strong>Lambda container images</strong>, because the decision engine carries XGBoost, pandas and geospatial libraries that will not fit in a zip. <strong>DynamoDB</strong> for plans, because every status change is appended to an audit trail and a plan cannot jump from draft to implemented. <strong>Bedrock Guardrails</strong> on top of our own number check, because the two catch different failures. <strong>Polly</strong>, because a morning advisory in spoken Hindi reaches people an email will not. And <strong>Budgets</strong> with an alarm, because a student project should not be able to run up a bill.
            </p>
            <p>
              Population comes from Meta’s HRSL dataset on the <strong>AWS Open Data Registry</strong>, read straight from S3.
            </p>
            {AWS_STATUS === 'templated' ? (
              <div className="aside-note">
                <b>Status, honestly.</b> The whole stack is one SAM template that validates with cfn-lint and deploys with <code>scripts/deploy.sh</code>. At the time of writing, the live Bedrock call has only been exercised through mocked tests. When the agent cannot reach Bedrock, the brief falls back to the template shown above, so the product still works.
              </div>
            ) : (
              <div className="aside-note">
                <b>Status.</b> The stack is deployed from one SAM template with <code>scripts/deploy.sh</code>. The demo video walks through the live Lambda, EventBridge, DynamoDB, SNS and CloudWatch resources.
              </div>
            )}
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="fought" title="What fought back">
          <div className="prose-col">
            <ol className="m-0 p-0 list-none grid gap-7">
              {[
                {
                  h: 'Our original data was wrong.',
                  b: 'The pre-hackathon version generated surface temperature from a formula. Checked against real Landsat for Delhi, it correlated at r = −0.47: hot where the city is cool. Everything you see here was rebuilt on observed data.',
                },
                {
                  h: 'Random validation lied to us.',
                  b: `A random spatial split scored r = ${blockR[0].toFixed(2)}–${blockR[1].toFixed(2)}. Holding out whole cities brought it down to ${totals.minR.toFixed(2)}–${totals.maxR.toFixed(2)} and exposed offsets of up to ${Math.max(Math.abs(biasR[0]), Math.abs(biasR[1])).toFixed(1)} °C. The architecture changed because of that test.`,
                },
                {
                  h: 'The data sources had opinions.',
                  b: 'WorldPop would not serve the range requests our pipeline needs, so we moved to Meta HRSL on the AWS Open Data Registry. OpenStreetMap’s Overpass API throttled us, so cooling-spot coverage is partial in some tiles. Every stage is cached per city so a failed run resumes instead of restarting.',
                },
                {
                  h: 'A formula can be valid and still mislead.',
                  b: 'Vulnerability includes building density. OSM building footprints are slow to fetch and off by default, so that term falls back to population density, which then counts twice. We would rather say so here than let the score look cleaner than it is.',
                },
                {
                  h: 'Placeholder costs decide the plan.',
                  b: 'The optimizer is only as honest as its inputs. With our planning-grade costs it never buys a tree. That is a reason to get local quotes, not a recommendation against trees.',
                },
                {
                  h: 'Language models are good at words and bad at numbers.',
                  b: 'Left alone, a model will round, merge or invent a figure, and a wrong number in a ward brief is worse than no brief. The number check, one corrective retry, a 20-second time budget and a deterministic template fallback turn that from a silent error into a contained, visible one.',
                },
                {
                  h: 'Operator noise and public alerts share a pipe.',
                  b: 'CloudWatch alarms currently publish to the same SNS topic as heat alerts, so a subscriber could get a Lambda error email. Splitting operator and citizen topics is the next infrastructure change.',
                },
              ].map((l, i) => (
                <li key={i} className="grid grid-cols-[2.25rem_1fr] gap-x-2">
                  <span className="ui num font-extrabold text-[1.35rem] leading-[1.3]" style={{ color: 'var(--heat)', fontStretch: '78%' }}>{i + 1}</span>
                  <div>
                    <h3 className="text-[1.2rem] font-bold leading-snug mb-1.5" style={{ fontStretch: '88%' }}>{l.h}</h3>
                    <p className="m-0" style={{ color: 'var(--ink-2)' }}>{l.b}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <Chapter id="limits" title="What it cannot tell you">
          <div className="prose-col">
            <p>
              We would rather a judge or a city official read this list from us than discover it.
            </p>
            <ul className="m-0 mb-8 pl-5 grid gap-2.5" style={{ color: 'var(--ink-2)' }}>
              <li>Surface temperature is not air temperature or heat stress.</li>
              <li>Risk is a <strong>relative ranking</strong> within a city, not a prediction of illness or death.</li>
              <li>Zones are 2 km analysis blocks ({fmt.int(delhiWards.of_wards)} in Delhi), not official wards. Age structure and informal-settlement data are not in this version.</li>
              <li>Cooling results are estimates clamped to published ranges. Costs are placeholders. Nothing here has been measured on a street.</li>
              <li>The uncertainty band was calibrated on the same folds it is scored on, so its coverage figures are optimistic.</li>
              <li>Only four cities use real data. The other sixteen are labelled synthetic previews.</li>
              <li>Weather features are one value per city, so with four cities the model cannot learn a reliable weather-to-temperature link.</li>
            </ul>
            <p>
              <strong>What’s next:</strong> local cost quotes and peer-reviewed cooling ranges, official ward boundaries, age data for vulnerability, a check of our top zones against a published city heat action plan, and separate SNS topics for operators and citizens.
            </p>
          </div>
        </Chapter>

        {/* ------------------------------------------------------------ */}
        <section id="credits" className="chapter pb-24" aria-labelledby="credits-h">
          <div className="prose-col ui text-[0.95rem]" style={{ color: 'var(--ink-2)' }}>
            <h2 id="credits-h" className="text-[1.6rem] font-extrabold mb-5" style={{ fontStretch: '80%', color: 'var(--ink)' }}>Credits and sources</h2>

            <h3 className="text-[1rem] font-bold mb-2" style={{ color: 'var(--ink)' }}>AI tools we used</h3>
            <ul className="m-0 mb-7 pl-5 grid gap-1.5">
              {AI_TOOLS.map((t) => <li key={t}>{t}</li>)}
            </ul>

            <h3 className="text-[1rem] font-bold mb-2" style={{ color: 'var(--ink)' }}>Data credits</h3>
            <p className="m-0 mb-7 leading-relaxed">
              Landsat data courtesy of the U.S. Geological Survey. Contains modified Copernicus Sentinel data. © ESA WorldCover project. Copernicus WorldDEM-30 © DLR e.V. 2010–2014 and © Airbus Defence and Space GmbH 2014–2018, provided under COPERNICUS by the European Union and ESA. Population: Meta Data for Good and CIESIN, Columbia University. © OpenStreetMap contributors. Weather data by Open-Meteo.com.
            </p>

            <h3 className="text-[1rem] font-bold mb-2" style={{ color: 'var(--ink)' }}>References</h3>
            <ol className="m-0 mb-7 pl-5 grid gap-1.5">
              {REFERENCES.map((r) => (
                <li key={r.url}><a href={r.url}>{r.text}</a></li>
              ))}
            </ol>

            <p className="m-0 pt-6 text-[0.875rem]" style={{ borderTop: '1px solid var(--rule)', color: 'var(--muted)' }}>
              Every figure on this page is exported from the repository by <code>scripts/export_blog_data.py</code>: model {model.version}, real-data tier for {CITY_IDS.map((c) => CITY_NAME[c]).join(', ')}. Code: <a href={REPO_URL}>{REPO_URL.replace('https://', '')}</a>. Built for Environmental Hacks (WeMakeDevs × AWS), Heat &amp; Water track.
            </p>
          </div>
        </section>
      </main>
    </>
  );
}
