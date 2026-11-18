// The #method page: how the atlas reads bills and what its signals mean. Static text.
export function methodMarkup(){
  const parts=[
    ['01','What is affected','Bills can carry many policy tags, legal effects, affected populations, local-government layers, and agencies. A tag can be explicitly supported or an inference, and we show that distinction.'],
    ['02','Who filed it','Author influence is based on independently verified roles: chamber leadership, committee chairmanship, relevant committee seats, and legislative tenure. We do not assign prominence just for party or media attention.'],
    ['03','Chance of a hearing','The atlas shows the strongest hearing signal supported by the record. A referral alone does not guarantee a hearing.'],
    ['04','Likelihood of passage','Passage requires a separate model: committee action, chamber calendars and votes, companion progress, cross-chamber support, deadlines, and executive position. No passage probabilities are currently claimed.'],
    ['05','What changes over time','Each action, bill version, fiscal note, referral, hearing notice, companion filing, and author role can add or change signals. The dataset preserves source timestamps and links to the state record.'],
    ['06','Who Luna is','Luna is the AI model that reads each bill’s full text. It writes the “In brief” line and the summary, adds topic, agency and search tags, and marks the passages its notes rest on. Everything it writes carries an AI label, can be wrong, and is never official: the bill text and the legislature’s record are. Review progress shows which bills it has read.'],
    ['07','Known limitations','Automated agency extraction from captions is incomplete. Predictions in early prefiling are particularly unstable, and committee assignments after the election must be verified before influence scoring.']
  ];
  return `<div class="section-head"><div><div class="section-overline">EXPLAINABLE SIGNALS</div><h2>Verified facts first. Forecasts second.</h2></div></div><div class="info-callout"><strong>A filed bill is not a viable bill by default.</strong> Hearing progress, author prominence, policy impact, and predicted enactment are separate dimensions. No numeric forecast appears without a measured historical basis and a stated confidence level.</div><figure class="hearing-guide"><figcaption>How to read hearing status</figcaption>
    <ol><li><strong>Referred</strong><span>The bill goes to a committee.</span></li>
    <li><strong>Scheduled</strong><span>A notice sets a hearing date.</span></li>
    <li><strong>Heard</strong><span>The record confirms a hearing took place.</span></li></ol>
    </figure><div class="method-grid">${parts.map(([,title,body])=>`<article class="method-card"><h3>${title}</h3><p>${body}</p></article>`).join('')}</div>`;
}
