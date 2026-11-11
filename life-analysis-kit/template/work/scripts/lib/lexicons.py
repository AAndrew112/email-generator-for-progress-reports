"""Small hand-made word lists for the language metrics.

They are deliberately simple and transparent. Lexicon methods misread sarcasm, quotation and
adolescent slang; treat every rate as a rough signal and extend the lists when a finding depends
on them. (Logged in out/00_methods_log.md.)
"""

PRONOUNS = {
    "i_me": {"i", "me", "my", "mine", "myself", "i'm", "i've", "i'll", "i'd"},
    "we": {"we", "us", "our", "ours", "ourselves", "we're", "we've", "we'll"},
    "you": {"you", "your", "yours", "yourself", "you're", "you've", "you'll"},
    "they": {"they", "them", "their", "theirs", "they're", "they've"},
}
MODALS = {
    "obligation": {"should", "shouldn't", "must", "ought", "supposed", "need", "needed", "needs"},
    "have_to": {"have to", "has to", "had to", "got to", "gotta"},
    "volition": {"want", "wanted", "wants", "choose", "chose", "decided", "decide", "wish", "hope"},
    "ability": {"can", "can't", "cannot", "couldn't", "able", "unable"},
    "future": {"will", "won't", "gonna", "going to"},
}
CERTAINTY = {"always", "never", "definitely", "obviously", "absolutely", "certainly", "clearly",
             "totally", "completely", "everyone", "nobody", "everything", "nothing"}
HEDGES = {"maybe", "perhaps", "probably", "possibly", "guess", "kinda", "sorta", "somewhat",
          "might", "seems", "apparently", "sort of", "kind of", "i think", "i guess"}
NEGATIONS = {"not", "no", "never", "don't", "doesn't", "didn't", "won't", "can't", "isn't", "wasn't"}
AGENCY_ACTIVE = {"i decided", "i chose", "i made", "i'm going to", "i will", "i started", "i quit",
                 "i told", "i asked", "i did", "i planned"}
AGENCY_PASSIVE = {"happened to me", "i had no choice", "i couldn't help", "it just happened",
                  "i got stuck", "i was made", "forced me", "made me"}
PAST = {"was", "were", "had", "did", "went", "said", "felt", "thought", "used to"}
PRESENT = {"is", "am", "are", "do", "does", "feel", "think", "have", "has"}
FILLERS = {"um", "uh", "like", "you know", "i mean", "basically", "literally"}
