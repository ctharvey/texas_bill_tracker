// Reader areas (issue #13): groups of bills built around who reads them, from the Legislative Council's official
// subjects plus title/caption keywords. Kept apart from POLICY_AREAS, so Luna's topic list and its cached reviews are
// unchanged. No DOM.
import {latestActivityDay} from '../../taxonomy.js';

// subjects: exact official subject names, or a prefix ending in '--' or an em dash for a whole subject family.
// keywords: tried on title + caption, for bills the subject index files elsewhere.
export const AREAS = [
  // Government technology & operations
  {id:"cybersecurity-it", name:"Cybersecurity & IT systems", group:"Government technology & operations",
   audience:"Agency IT and security staff, technology vendors",
   subjects:["INTERNET", "EMAIL & ELECTRONIC COMMUNICATIONS", "TELEPHONES & TELEPHONE DIRECTORIES", "Electronic Information Systems", "COMPUTERS & SOFTWARE", "CYBER COMMAND, TEXAS", "INFORMATION RESOURCES, DEPARTMENT OF", "DIGITAL SIGNATURES", "TERRORISM & INTERNAL SECURITY", "BROADBAND DEVELOPMENT OFFICE", "BROADBAND NETWORKS", "Utilities--Telecommunications", "TELECONFERENCING", "VIDEOCONFERENCING"],
   keywords:/cybersecurity|information security|ransomware|security breach|information technology|information resources|broadband/i},
  {id:"privacy", name:"Privacy & personal data", group:"Government technology & operations",
   audience:"Privacy officers, consumer and civil-liberties groups",
   subjects:["Protection of Personal Information", "Health--Privacy/Use of Information", "CONSUMER REPORTING AGENCIES", "CREDIT REPORTS", "VIDEO CAMERAS"],
   keywords:/privacy|personal identifying information|personal data|biometric|data broker|facial recognition/i},
  {id:"records-transparency", name:"Records, transparency & data governance", group:"Government technology & operations",
   audience:"Records officers, journalists, open-government groups",
   subjects:["Open Records", "Open Meetings", "PUBLIC NOTICE", "VITAL STATISTICS & RECORDS", "BIRTH & DEATH CERTIFICATES", "STATE AGENCIES' RULES"],
   keywords:/data governance|records retention|records management|open data|public information act|open meetings/i},
  {id:"artificial-intelligence", name:"Artificial intelligence", group:"Government technology & operations",
   audience:"Technology, policy and civil-liberties groups",
   subjects:["Artificial Intelligence", "ARTIFICIAL INTELLIGENCE COUNCIL, TEXAS", "ARTIFICIAL INTELLIGENCE, TEXAS DEPARTMENT OF", "TEXAS DEPARTMENT OF ARTIFICIAL INTELLIGENCE ACT"],
   keywords:/artificial intelligence|machine learning|deepfake|generative AI/i},
  {id:"accessibility", name:"Accessibility", group:"Government technology & operations",
   audience:"Accessibility coordinators, disability advocates",
   subjects:["ASSISTIVE TECHNOLOGY DEVICES", "SIGN LANGUAGE & SIGN LANGUAGE INTERPRETERS"],
   keywords:/\baccessibility\b|americans with disabilities act|assistive technolog|screen reader|braille|sign language/i},
  {id:"procurement", name:"Procurement & state contracting", group:"Government technology & operations",
   audience:"Agency purchasing staff, vendors, HUB-certified businesses",
   subjects:["Purchasing--", "SURPLUS PROPERTY", "CONTRACTORS & SUBCONTRACTORS"],
   keywords:/procurement|state purchasing|competitive bid|historically underutilized/i},
  {id:"agency-operations", name:"State agency operations & oversight", group:"Government technology & operations",
   audience:"Agency leadership and government-affairs staff",
   subjects:["WHISTLEBLOWERS", "State Agencies, Boards & Commissions", "State Agencies, Boards & Commissions--", "Sunset--", "Sunset\u2014", "SUNSET ADVISORY COMMISSION", "State Finances--", "AUDITOR, STATE", "AUDITS & AUDITORS", "LEGISLATIVE BUDGET BOARD", "ADMINISTRATIVE HEARINGS, STATE OFFICE OF", "Interim Studies", "FACILITIES COMMISSION, TEXAS", "State Officers", "Salaries & Expenses", "Fees & Other Nontax Revenue--State", "Public Lands, Buildings & Resources", "STATE CAPITOL BUILDING & GROUNDS", "STATE PRESERVATION BOARD", "Ethics", "ETHICS COMMISSION, TEXAS", "LOBBYISTS & LOBBYING"],
   keywords:/state agenc(?:y|ies)|sunset review|state auditor/i},
  {id:"public-employees", name:"Public employees & pensions", group:"Government technology & operations",
   audience:"State and local employees, retirees, public-sector unions",
   subjects:["GRIEVANCE PROCEDURES", "State Employees", "Retirement Systems--", "EMPLOYEES RETIREMENT SYSTEM OF TEXAS (ERS)", "DEFERRED COMPENSATION", "City Government--Employees/Officers", "County Government--Employees/Officers", "TEXAS STATE EMPLOYEE PATHWAYS ACT", "ASSAULT LEAVE"],
   keywords:/state employee|public employee|retirement system|employees retirement/i},
  {id:"constitutional-amendments", name:"Constitutional amendments", group:"Government technology & operations",
   audience:"Voters, election officials, civic groups",
   subjects:["Resolutions--Constitutional Amendments"],
   keywords:/constitutional amendment|amendment to the texas constitution/i},
  {id:"emergency-management", name:"Disasters & emergency management", group:"Government technology & operations",
   audience:"Emergency managers, local officials, relief organizations",
   subjects:["Disaster Preparedness & Relief", "EMERGENCY MANAGEMENT, TEXAS DIVISION OF", "FLOODS", "ALERT SYSTEM"],
   keywords:/disaster|emergency management|flooding|flood (?:control|plain|warning|mitigation|insurance)|hurricane|wildfire/i},
  // People & communities
  {id:"children-youth", name:"Children & youth", group:"People & communities",
   audience:"Child advocates, foster-care and juvenile-justice groups, pediatric providers",
   subjects:["Minors--", "Family--Child Protection", "Family--Parent & Child", "Family--Juvenile Delinquency", "Family--Child Support", "Crimes--Juvenile", "Juvenile Boards & Officers", "JUVENILE JUSTICE DEPARTMENT, TEXAS", "FAMILY & PROTECTIVE SERVICES, DEPARTMENT OF", "FOSTER CARE", "FOSTER CARE PLACEMENT, OVERSIGHT ADVISORY COUNCIL ON", "FAITH-BASED FOSTER CARE ENHANCEMENT ACT", "CHILD ABUSE", "CHILD WITNESSES", "CHILD CUSTODY", "CONSERVATORSHIP", "PATERNITY", "Day Care", "Human Services--Child Services", "Health--Children's Insurance", "PRESCHOOL & PREKINDERGARTEN", "YOUTH CAMPS", "BOARD OF YOUTH HEALTH AND SAFETY", "OFFICE OF YOUTH HEALTH AND SAFETY", "BULLYING", "PARENTAL CONSENT", "PARENTAL NOTIFICATION", "PARENTAL RIGHTS", "DROPOUTS & AT-RISK STUDENTS"],
   keywords:/foster care|juvenile|child abuse|child care|child-care|child protective|child welfare|youth camp/i},
  {id:"victims-family-violence", name:"Victims, family violence & sexual assault", group:"People & communities",
   audience:"Victim services, shelters, advocacy groups, prosecutors",
   subjects:["Family--Family Violence", "Crimes--Against Persons--Sexual", "SEXUAL ABUSE", "SEXUAL ASSAULT", "SEXUAL HARASSMENT", "SEXUAL OFFENDERS", "STALKING", "PROTECTIVE ORDERS", "HUMAN TRAFFICKING", "HARASSMENT", "Crime Victims Compensation", "CRIME VICTIMS", "SHARON RADEBAUGH FAMILY VIOLENCE PROTECTION ACT", "PROSTITUTION"],
   keywords:/family violence|domestic violence|sexual assault|protective order|human trafficking|stalking|crime victim/i},
  {id:"womens-maternal-health", name:"Women's & maternal health", group:"People & communities",
   audience:"Women's health providers and advocates, maternal-health groups",
   subjects:["Women", "PREGNANCY & CHILDBIRTH", "Abortion", "FAMILY PLANNING & BIRTH CONTROL", "MAMMOGRAPHY", "TEXAS MATERNAL MORTALITY AND MORBIDITY REVIEW COMMITTEE", "INFERTILITY", "SURROGATE MOTHERS", "PROTECT SURVIVORS' HEALTH CARE DECISIONS ACT", "HUMAN PAPILLOMAVIRUS"],
   keywords:/maternal|pregnan|postpartum|abortion|breast cancer|cervical cancer|prenatal/i},
  {id:"mental-health", name:"Mental health & substance use", group:"People & communities",
   audience:"Behavioral-health providers, recovery and peer-support groups",
   subjects:["Mental Health & Substance Abuse", "Alcoholism & Drug Abuse", "BEHAVIORAL HEALTH EXECUTIVE COUNCIL, TEXAS", "CIVIL COMMITMENT", "MENTAL INCOMPETENCY", "CHEMICAL DEPENDENCY COUNSELORS", "PROFESSIONAL COUNSELORS", "DRUG COURTS", "RURAL MENTAL HEALTH AND INTELLECTUAL DISABILITY SERVICES, OFFICE OF", "CORRECTIONAL OFFICE ON OFFENDERS WITH MEDICAL OR MENTAL IMPAIRMENTS, TEXAS", "FETAL ALCOHOL SPECTRUM DISORDER ADVISORY COUNCIL", "NEEDLES & SYRINGES"],
   keywords:/mental health|behavioral health|substance use disorder|suicide prevention|opioid|overdose/i},
  {id:"disability", name:"Disability", group:"People & communities",
   audience:"People with disabilities, families, disability-services providers",
   subjects:["Disabilities, Persons with", "DEVELOPMENTAL DISABILITIES, TEXAS COUNCIL FOR", "GOVERNOR'S COMMITTEE ON PEOPLE WITH DISABILITIES", "AUTISM & PERVASIVE DEVELOPMENTAL DISORDERS", "STATEWIDE INTELLECTUAL AND DEVELOPMENTAL DISABILITY COORDINATING COUNCIL", "TEXAS A&M UNIVERSITY CENTER ON DISABILITY & DEVELOPMENT", "UNIVERSITY OF TEXAS AT AUSTIN CENTER FOR DISABILITY STUDIES", "Education--Primary & Secondary--Special", "ASSISTIVE TECHNOLOGY DEVICES", "SIGN LANGUAGE & SIGN LANGUAGE INTERPRETERS", "GUARDIANS & WARDS"],
   keywords:/persons? with (?:a )?disabilit|intellectual (?:and|or) developmental disabilit|special education|autism/i},
  {id:"older-texans", name:"Older Texans & long-term care", group:"People & communities",
   audience:"Seniors, family caregivers, long-term-care providers",
   subjects:["Aging", "Nursing Homes", "LONG-TERM CARE", "LONG-TERM CARE OMBUDSMAN, STATE", "ASSISTED LIVING FACILITIES", "ALZHEIMER'S DISEASE", "DEMENTIA PREVENTION AND RESEARCH INSTITUTE OF TEXAS", "HOME HEALTH CARE", "GUARDIANS & WARDS", "Probate--Durable Power of Attorney", "MEDICARE"],
   keywords:/nursing (?:home|facilit)|long-term care|assisted living|elderly|dementia|alzheimer/i},
  {id:"veterans-military", name:"Veterans & military", group:"People & communities",
   audience:"Veterans, service members and their families, veterans organizations",
   subjects:["U.S. NAVY", "Military & Veterans", "VETERANS COMMISSION, TEXAS", "VETERANS' LAND BOARD", "ADJUTANT GENERAL", "NATIONAL GUARD, TEXAS", "STATE GUARD, TEXAS", "GREEN STAR SERVICE BANNER"],
   keywords:/veteran|military|armed forces|national guard|service member/i},
  {id:"rural-texas", name:"Rural Texas", group:"People & communities",
   audience:"Rural communities, rural hospitals and providers, county officials",
   subjects:["Health--Rural", "Utilities--Telecommunications--Rural", "ECONOMICALLY DISTRESSED AREAS", "COLONIAS", "RURAL MENTAL HEALTH AND INTELLECTUAL DISABILITY SERVICES, OFFICE OF", "BROADBAND DEVELOPMENT OFFICE", "BROADBAND NETWORKS"],
   keywords:/\brural\b|colonias|broadband/i},
  {id:"public-assistance", name:"Food & public assistance", group:"People & communities",
   audience:"Food banks, benefits navigators, anti-poverty groups",
   subjects:["Human Services--Food Programs", "Human Services--Direct Assistance", "Human Services--General", "ELECTRONIC BENEFITS TRANSFER", "INFORMATION & REFERRAL NETWORK, TEXAS"],
   keywords:/supplemental nutrition|\bSNAP\b|temporary assistance for needy|\bTANF\b|\bWIC\b|food bank|food insecur/i},
  // Services, professions & money
  {id:"health-coverage", name:"Health insurance & coverage", group:"Services, professions & money",
   audience:"Patients, insurers, health plans, benefits advocates",
   subjects:["HEALTH & HUMAN SERVICES OFFICE OF THE OMBUDSMAN", "Insurance--Health & Accident", "Insurance--Life, Health & Accident", "Human Services--Medical Assistance", "MEDICAID", "MEDICAID REFORM TASK FORCE", "Health--Children's Insurance", "MANAGED CARE", "HEALTH MAINTENANCE ORGANIZATIONS", "PHARMACY BENEFIT MANAGERS", "Health--Indigent Health Care", "MEDICARE"],
   keywords:/health benefit plan|health insurance|medicaid|pharmacy benefit|managed care/i},
  {id:"licensed-professions", name:"Licensed professions", group:"Services, professions & money",
   audience:"Licensed professionals, licensing boards, professional associations",
   subjects:["ENVIRONMENTAL SANITATION & SANITARIANS", "Occupational Regulation--", "LICENSING & REGULATION, TEXAS COMMISSION OF", "LICENSING & REGULATION, TEXAS DEPARTMENT OF", "NURSING, TEXAS BOARD OF", "MEDICAL BOARD, TEXAS", "PHARMACY, TEXAS STATE BOARD OF", "PHYSICIAN ASSISTANT BOARD, TEXAS", "PHYSICIAN ASSISTANT LICENSURE COMPACT", "PA LICENSURE COMPACT COMMISSION", "COSMETOLOGY LICENSURE COMPACT COMMISSION", "SOCIAL WORK LICENSURE COMPACT COMMISSION", "PLUMBING EXAMINERS, TEXAS STATE BOARD OF", "TEXAS REAL ESTATE COMMISSION", "REAL ESTATE APPRAISERS", "LAW EXAMINERS, BOARD OF", "STATE BAR OF TEXAS", "CONTINUING EDUCATION", "COSMETOLOGISTS", "DENTISTS & DENTISTRY", "ENGINEERS & ENGINEERING", "MASSAGE THERAPY & MASSAGE THERAPISTS", "NURSES & NURSE AIDES", "PHARMACIES & PHARMACISTS", "PHYSICAL THERAPISTS", "PHYSICIAN ASSISTANTS", "PHYSICIANS", "PLUMBERS & PLUMBING", "PROSTHETISTS & PROSTHETICS", "ROOFING CONTRACTORS", "REROOFING CONTRACTOR ADVISORY BOARD", "SOCIAL WORK & SOCIAL WORKERS", "VETERINARIANS", "BUILDING INSPECTORS", "MORTGAGE LOAN ORIGINATORS", "BAIL BONDSMEN", "CHEMICAL DEPENDENCY COUNSELORS", "PROFESSIONAL COUNSELORS", "Notaries", "Lawyers"],
   keywords:/licensure compact/i},
  {id:"courts-civil-justice", name:"Courts, civil justice & legal aid", group:"Services, professions & money",
   audience:"Attorneys, courts, legal-aid and indigent-defense providers",
   subjects:["INTELLECTUAL PROPERTY", "Family--Marriage Relationship", "Family--General", "MARRIAGE LICENSES", "MARRIAGE CEREMONIES", "SAME-SEX MARRIAGE", "Civil Remedies & Liabilities", "Courts--", "Lawyers", "EVIDENCE", "MEDIATION, DISPUTE RESOLUTION, & ARBITRATION", "ATTORNEY'S FEES", "SUPREME COURT", "CRIMINAL APPEALS, COURT OF", "COURT ADMINISTRATION, OFFICE OF", "JUDICIAL DISTRICTS BOARD", "JUSTICE OF THE PEACE", "MAGISTRATES", "WITNESSES", "INDIGENT LEGAL SERVICES", "INDIGENT DEFENSE COMMISSION, TEXAS", "Criminal Procedure--Defense Counsel", "DEFENDER GENERAL, OFFICE OF", "CAPITAL AND FORENSIC WRITS, OFFICE OF", "HABEAS CORPUS", "WRONGFUL IMPRISONMENT", "Probate--Wills & Admin of Estates", "Property Interests--Trusts", "TRUSTS"],
   keywords:/legal aid|indigent defense|access to justice|civil legal services/i},
  {id:"consumers-finance", name:"Consumers & personal finance", group:"Services, professions & money",
   audience:"Consumers, consumer advocates, lenders and financial firms",
   subjects:["INSURANCE RATES", "FINANCE COMMISSION OF TEXAS", "Consumer Protection", "Financial--", "CREDIT & DEBIT CARDS", "CREDIT SCORING", "CREDIT SERVICE ORGANIZATIONS", "DEFERRED PRESENTMENT TRANSACTIONS", "LOANS", "DEBT", "ADVERTISING", "PACKAGING & LABELING REQUIREMENTS", "TICKET SCALPING", "CONSUMER REPORTING AGENCIES", "CREDIT REPORTS", "Property Interests--Mortgages & Liens", "STUDENT LOANS", "Business & Commerce--Trade Practices"],
   keywords:/consumer protection|deceptive trade|payday|credit report|debt collect/i},
  {id:"nonprofits", name:"Nonprofits & charities", group:"Services, professions & money",
   audience:"Nonprofits, charities, volunteer organizations",
   subjects:["Charitable & Nonprofit Organizations", "GIFTS & DONATIONS", "VOLUNTEERS"],
   keywords:/nonprofit organization|charitable organization/i},
  {id:"first-responders", name:"Police, fire & EMS", group:"Services, professions & money",
   audience:"Peace officers, firefighters, EMS and 9-1-1 staff, their associations",
   subjects:["Law Enforcement", "PUBLIC SAFETY, DEPARTMENT OF", "FIRE SAFETY & PREVENTION", "Fire Fighters & Police--", "PEACE OFFICERS", "LAW ENFORCEMENT, TEXAS COMMISSION ON", "Health--Emergency Services & Personnel", "AMBULANCES", "SHERIFFS", "FIRE MARSHAL", "TELECOMMUNICATORS", "EMERGENCY COMMUNICATIONS, COMMISSION ON STATE", "EMERGENCY VEHICLES", "Retirement Systems--Police & Firefighters"],
   keywords:/peace officer|firefighter|fire fighter|first responder|emergency medical|\bEMS\b|9-1-1/i},
  {id:"teachers-school-staff", name:"Teachers & school staff", group:"Services, professions & money",
   audience:"Teachers, school employees, their associations",
   subjects:["Education--Primary & Secondary--Teachers", "Education--Primary & Secondary--Other School Personnel", "Retirement Systems--Teachers", "EDUCATOR CERTIFICATION, STATE BOARD FOR", "STAFF DEVELOPMENT & TRAINING"],
   keywords:/teacher|educator|school employee|school personnel/i},
  {id:"higher-ed-workforce", name:"Higher education & workforce training", group:"Services, professions & money",
   audience:"Colleges and universities, students, workforce boards, employers",
   subjects:["RESEARCH & DEVELOPMENT", "Education--Primary & Secondary--Vocational", "Education--Higher--", "Education--Junior College Districts", "EDUCATION--HIGHER--CURRICULUM", "HIGHER EDUCATION COORDINATING BOARD, TEXAS", "OFFICE OF THE OMBUDSMAN, TEXAS HIGHER EDUCATION COORDINATING BOARD", "Labor--Workforce Development", "WORKFORCE DEVELOPMENT BOARDS", "SCHOLARSHIPS", "STUDENT LOANS", "GRADUATE STUDENTS", "TRANSFER STUDENTS", "ADULT EDUCATION", "TEXAS A&M UNIVERSITY", "TEXAS SOUTHERN UNIVERSITY", "TEXAS SOUTHERN UNIVERSITY COLLEGE OF MEDICINE", "TEXAS TECH UNIVERSITY HEALTH SCIENCES CENTER", "UNIVERSITY OF TEXAS AT EL PASO", "UNIVERSITY OF TEXAS AT SAN ANTONIO", "UNIVERSITY OF TEXAS HEALTH SCIENCE CENTER AT HOUSTON", "UNIVERSITY OF TEXAS RIO GRANDE VALLEY", "UNIVERSITY OF TEXAS SYSTEM", "RIO GRANDE VALLEY SCHOOL OF LAW", "TEXAS A&M AGRILIFE", "TEXAS A&M AGRILIFE EXTENSION SERVICE", "UNIVERSITY OF TEXAS AT AUSTIN BUREAU OF ECONOMIC GEOLOGY"],
   keywords:/institution of higher education|universit|community college|workforce training|apprenticeship program/i},
  {id:"property-tax-homeowners", name:"Property tax & homeowners", group:"Services, professions & money",
   audience:"Homeowners, appraisal districts, taxing units",
   subjects:["Taxation--Property-", "Property Interests--Homestead", "Taxation--School District", "COUNTY TAX ASSESSOR-COLLECTORS", "Property Interests--Property Owners Association"],
   keywords:/property tax|ad valorem|appraisal district|homestead/i},
  {id:"small-business", name:"Small & minority-owned business", group:"Services, professions & money",
   audience:"Small-business owners, chambers, HUB-certified firms",
   subjects:["Business & Commerce--Small Business & Minority Business"],
   keywords:/small business|minority-owned|woman-owned|women-owned|historically underutilized|microbusiness/i}
];

export const AREA_GROUPS = [...new Set(AREAS.map(a => a.group))];
export const AREA_BY_ID = new Map(AREAS.map(a => [a.id, a]));

const family = rule => rule.endsWith('-') || rule.endsWith('\u2014');
export const subjectMatches = (rule, subject) => family(rule) ? subject.startsWith(rule) : subject === rule;

// Why a bill is in an area: which of its official subjects belong to it, and whether its title or caption has one of
// the area's keywords.
export function areaMatch(bill, area) {
  const subjects = (bill.subjects || []).filter(s => typeof s === 'string' && area.subjects.some(r => subjectMatches(r, s)));
  return {subjects, keyword: area.keywords.test(`${bill.title || ''} ${bill.caption || ''}`)};
}

const cache = new WeakMap();
// The ids of the areas a bill is in, in AREAS order. Bills are not changed; the answer is remembered per bill object.
export function billAreas(bill) {
  if (!bill || typeof bill !== 'object') return [];
  let ids = cache.get(bill);
  if (!ids) {
    ids = AREAS.filter(area => { const m = areaMatch(bill, area); return m.subjects.length > 0 || m.keyword; }).map(a => a.id);
    cache.set(bill, ids);
  }
  return ids;
}
export const inArea = (bill, id) => billAreas(bill).includes(id);

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const daysBefore = (day, n) => new Date(Date.parse(`${day}T12:00:00Z`) - n * 864e5).toISOString().slice(0, 10);

// Every area with its number of bills and how many had a dated action in the `days` days up to `today`.
export function areaCounts(bills, today, days = 7) {
  const since = DAY.test(today || '') ? daysBefore(today, days - 1) : null;
  const rows = new Map(AREAS.map(area => [area.id, {area, count: 0, moved: 0}]));
  for (const bill of bills) {
    const ids = billAreas(bill);
    if (!ids.length) continue;
    const day = since ? latestActivityDay([bill], today) : null;
    for (const id of ids) {
      const row = rows.get(id);
      row.count++;
      if (day && day >= since) row.moved++;
    }
  }
  return [...rows.values()];
}

// The agencies an area's bills name most often: [{id, count}], most first, then by id.
export function topAgencies(bills, limit = 5, skip = new Set()) {
  const counts = new Map();
  for (const bill of bills) {
    for (const id of new Set((bill.agencies || []).map(a => a?.id).filter(Boolean))) {
      if (!skip.has(id)) counts.set(id, (counts.get(id) || 0) + 1);
    }
  }
  return [...counts].map(([id, count]) => ({id, count})).sort((a, b) => b.count - a.count || a.id.localeCompare(b.id)).slice(0, limit);
}
