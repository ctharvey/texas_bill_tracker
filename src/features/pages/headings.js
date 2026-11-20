// The about pages' headings ([title, subtitle]), shared by the app's views and the static pages the data run builds
// from the agent's render of these views (SEO chunk 5 phase 3), so both say the same thing.
export const ABOUT_HEADINGS = {
  method: ['How the atlas works.', 'Signals and uncertainty are displayed separately from verified legislative actions.'],
  saving: ['Save your work.', 'Keep your watchlist and views on one device, carry them in a link or file, or sync them privately.'],
  data: ['Behind the tracker.', 'Understand coverage, refreshes, and how to load or export bill data.'],
};
// Home and Today, whose static copies (phase 4) are drawn as of the snapshot's time.
export const PAGE_HEADINGS = {
  home: ['This session, at a glance.', 'What changed on your bills, what moved today, upcoming hearings and Luna\u2019s newest reviews.'],
  today: ['Today at the Lege.', 'Bills with a recorded action that day, by type of action. Dates follow Texas time.'],
};
