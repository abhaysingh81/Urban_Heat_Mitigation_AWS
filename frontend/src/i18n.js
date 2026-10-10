import { createContext, useContext } from 'react';

// UI strings for the decision pages + navigation. Hindi is written by hand
// (short, plain words) and should be reviewed by a native speaker before
// any official use.
const STRINGS = {
  en: {
    nav_heat_map: 'Heat Map', nav_drivers: 'Heat Drivers', nav_scenarios: 'Scenarios',
    nav_risk: 'Ward Risk', nav_plan: 'Action Plan', nav_model: 'Model Card', nav_citizen: 'Citizen View',
    language: 'Language', preview_banner: 'Synthetic preview — illustrative data, not real measurements.',
    real_badge: 'Real satellite data',
    risk_title: 'Which wards need help first?', risk_sub: 'Risk = heat × people exposed × vulnerability. A relative ranking, not a prediction of harm.',
    rank: 'Rank', ward: 'Ward / zone', risk: 'Risk', heat: 'Heat', people: 'People', vulnerability: 'Vulnerability',
    avg_temp: 'Avg surface temp', select_ward: 'Plan for this ward',
    today: 'Today', alert: 'Alert', stale: 'Using last saved forecast', forecast_high: 'Forecast high',
    plan_title: 'What should we build, and for how much?', plan_sub: 'Set a budget. We rank actions by cooling per rupee; the equity slider favours vulnerable areas.',
    budget: 'Budget (₹ crore)', equity: 'Equity weight', equity_hint: '0 = most cooling per rupee · 1 = favour the most vulnerable',
    tree_survival: 'Tree survival', interventions: 'Interventions', build_plan: 'Build plan', building: 'Building…',
    people_protected: 'People protected', cost_per_person: '₹ per person', cooling: 'Estimated cooling', spent: 'Spent',
    estimate_note: 'Estimates from published ranges, not guarantees.', efficiency_plan: 'Efficiency plan', equity_plan: 'Equity plan',
    high_vuln_share: 'Spend in high-vulnerability cells', beneficiary_vuln: 'Avg vulnerability of people helped', timeline: 'Cooling over time (years)', actions: 'Planned actions',
    status: 'Plan status', approve: 'Approve', mark_done: 'Mark implemented', make_brief: 'Write ward brief (English + Hindi)',
    brief_for: 'Brief for ward', download_pdf: 'Download PDF', source: 'Source',
    model_title: 'How this was built', model_sub: 'Data sources, accuracy on cities the model never saw, and limits.',
    citizen_title: 'Heat today', use_location: 'Use my location', nearest_cool: 'Nearest places to cool down',
    report_title: 'Help us improve — report a problem here', no_shade: 'No shade', no_water: 'No drinking water',
    very_hot: 'Very hot here', thanks: 'Thank you — report received.', away: 'm away', directions: 'Directions',
    ward_rank_line: 'Your area ranks', of: 'of',
    export_csv: 'Download CSV', export_geojson: 'Download GeoJSON', listen: 'Listen: Hindi audio advisory',
    onb_title: 'Welcome — read this in 30 seconds', onb_1: 'Ward Risk shows which areas need help first: heat × people × vulnerability.', onb_2: 'Action Plan turns a budget into a ranked, costed list of cooling actions, and writes a Hindi + English brief.', onb_3: 'Everything marked estimate comes from published ranges. Cities labelled preview use synthetic data.', onb_ok: 'Got it',
    loading: 'Loading…', error: 'Could not load data. Is the backend running?', real_only: 'This view needs real-data cities (Delhi, Mumbai, Jaipur, Bengaluru). Select one in the sidebar.',
  },
  hi: {
    nav_heat_map: 'गर्मी का नक्शा', nav_drivers: 'गर्मी के कारण', nav_scenarios: 'परिदृश्य',
    nav_risk: 'वार्ड जोखिम', nav_plan: 'कार्य योजना', nav_model: 'मॉडल कार्ड', nav_citizen: 'नागरिक दृश्य',
    language: 'भाषा', preview_banner: 'नकली पूर्वावलोकन — उदाहरण डेटा, असली माप नहीं।',
    real_badge: 'असली उपग्रह डेटा',
    risk_title: 'किन वार्डों को सबसे पहले मदद चाहिए?', risk_sub: 'जोखिम = गर्मी × प्रभावित लोग × कमज़ोरी। यह तुलनात्मक क्रम है, नुकसान का पूर्वानुमान नहीं।',
    rank: 'क्रम', ward: 'वार्ड / ज़ोन', risk: 'जोखिम', heat: 'गर्मी', people: 'लोग', vulnerability: 'कमज़ोरी',
    avg_temp: 'औसत सतही तापमान', select_ward: 'इस वार्ड की योजना',
    today: 'आज', alert: 'चेतावनी', stale: 'पिछला सहेजा गया पूर्वानुमान', forecast_high: 'अधिकतम अनुमान',
    plan_title: 'क्या बनाएँ, और कितने खर्च में?', plan_sub: 'बजट तय करें। हम प्रति रुपया ठंडक के हिसाब से कदम चुनते हैं; समानता स्लाइडर कमज़ोर इलाकों को प्राथमिकता देता है।',
    budget: 'बजट (₹ करोड़)', equity: 'समानता भार', equity_hint: '0 = प्रति रुपया सबसे ज़्यादा ठंडक · 1 = सबसे कमज़ोर को प्राथमिकता',
    tree_survival: 'पेड़ बचने की दर', interventions: 'उपाय', build_plan: 'योजना बनाएँ', building: 'बन रही है…',
    people_protected: 'सुरक्षित लोग', cost_per_person: '₹ प्रति व्यक्ति', cooling: 'अनुमानित ठंडक', spent: 'खर्च',
    estimate_note: 'प्रकाशित सीमाओं पर आधारित अनुमान, गारंटी नहीं।', efficiency_plan: 'दक्षता योजना', equity_plan: 'समानता योजना',
    high_vuln_share: 'अधिक कमज़ोर इलाकों में खर्च', beneficiary_vuln: 'सहायता पाने वालों की औसत कमज़ोरी', timeline: 'समय के साथ ठंडक (वर्ष)', actions: 'योजनाबद्ध कदम',
    status: 'योजना की स्थिति', approve: 'मंज़ूर करें', mark_done: 'लागू हुई चिह्नित करें', make_brief: 'वार्ड ब्रीफ़ लिखें (अंग्रेज़ी + हिंदी)',
    brief_for: 'वार्ड का ब्रीफ़', download_pdf: 'PDF डाउनलोड', source: 'स्रोत',
    model_title: 'यह कैसे बना', model_sub: 'डेटा स्रोत, अनदेखे शहरों पर सटीकता, और सीमाएँ।',
    citizen_title: 'आज की गर्मी', use_location: 'मेरा स्थान उपयोग करें', nearest_cool: 'ठंडक के सबसे नज़दीकी स्थान',
    report_title: 'सुधार में मदद करें — यहाँ की समस्या बताएँ', no_shade: 'छाया नहीं', no_water: 'पीने का पानी नहीं',
    very_hot: 'यहाँ बहुत गर्मी है', thanks: 'धन्यवाद — रिपोर्ट मिल गई।', away: 'मी दूर', directions: 'रास्ता',
    ward_rank_line: 'आपका इलाका', of: 'में से',
    export_csv: 'CSV डाउनलोड', export_geojson: 'GeoJSON डाउनलोड', listen: 'सुनें: हिंदी ऑडियो सलाह',
    onb_title: 'स्वागत है — 30 सेकंड में पढ़ें', onb_1: 'वार्ड जोखिम बताता है कि किन इलाकों को पहले मदद चाहिए: गर्मी × लोग × कमज़ोरी।', onb_2: 'कार्य योजना बजट को ठंडक के कदमों की क्रमबद्ध, लागत वाली सूची में बदलती है, और हिंदी + अंग्रेज़ी ब्रीफ़ लिखती है।', onb_3: 'जो "अनुमान" लिखा है वह प्रकाशित सीमाओं पर आधारित है। "पूर्वावलोकन" वाले शहर नकली डेटा पर हैं।', onb_ok: 'ठीक है',
    loading: 'लोड हो रहा है…', error: 'डेटा लोड नहीं हो सका। क्या बैकएंड चल रहा है?', real_only: 'इस दृश्य के लिए असली डेटा वाले शहर (दिल्ली, मुंबई, जयपुर, बेंगलुरु) चाहिए। साइडबार में चुनें।',
  },
};

export const LangContext = createContext({ lang: 'en', setLang: () => {}, t: (k) => k });

export const useLang = () => useContext(LangContext);
export { STRINGS };
