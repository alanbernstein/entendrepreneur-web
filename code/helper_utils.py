from collections import defaultdict
from nltk.corpus import wordnet as wn
from nltk.stem import WordNetLemmatizer
from nltk.stem.porter import PorterStemmer
from portmanteau import Portmanteau
from rhyme import Rhyme
from global_constants import MAX_NEIGHBORS
import io
import pdb

###############################
### DEFINE HELPER FUNCTIONS ###
###############################

def parse_options(args):
    '''
    For each option (identified by a preceding '--'), store it as a key mapping to 'True' in the 'options' dict
    '''
    options = defaultdict(bool)
    for arg in args:
        if arg[:2] == '--':
           options[arg[2:]] = True
    return options

def load_fasttext_vectors(fname):
    fin = io.open(fname, 'r', encoding='utf-8', newline='\n', errors='ignore')
    n, d = map(int, fin.readline().split())
    data = {}
    for line in fin:
        tokens = line.rstrip().split(' ')
        data[tokens[0]] = map(float, tokens[1:])
    return data

def alternative_grapheme_capitalizations(grapheme):
    '''
    For a given grapheme, returns a list containing:
    1) the grapheme as-is
    2) the grapheme all-lower-cased
    3) the grapheme all-lowercased except for the first letter, which is capitalized
    '''

    capitalization_alternatives = [grapheme]
    capitalization_alternatives.append(grapheme.lower())
    if len(grapheme) == 1:
        capitalization_alternatives.append(grapheme[0].upper())
    elif len(grapheme) > 1:
        capitalization_alternatives.append(grapheme[0].upper()+grapheme[1:].lower())
    return capitalization_alternatives


def validate_input(input_string, recognized_graphemes):
    '''
    Verify that the input is comprised of two graphemes, and that both graphemes are present in Word2Vec
    '''
    if type(input_string) is not str or len(input_string.split()) != 2:
        status = 1
        message = 'Error: Input should be of the form "[word1] [word2]"'
    else:
        grapheme1, grapheme2 = input_string.split()

        # Each grapheme exists in word2vec either:
        # 1) as-is
        # 2) all lower-cased
        # 3) all lower-cased except for first letter
        grapheme1_exists = any([g in recognized_graphemes for g in alternative_grapheme_capitalizations(grapheme1)])
        grapheme2_exists = any([g in recognized_graphemes for g in alternative_grapheme_capitalizations(grapheme2)])

        if not grapheme1_exists and grapheme2_exists:
            status = 1
            message = "Error: '{}' is not a recognized word, please check the spelling".format(grapheme1)
        elif grapheme1_exists and not grapheme2_exists:
            status = 1
            message = "Error: '{}' is not a recognized word, please check the spelling".format(grapheme2)
        elif not grapheme1_exists and not grapheme2_exists:
            status = 1
            message = "Error: neither '{}' nor '{}' is a recognized word, please check the spelling".format(grapheme1, grapheme2)
        else:
            status = 0
            message = ''

    return status, message


def parse_input(input_string):
    grapheme1, grapheme2 = input_string.split()
    return grapheme1, grapheme2


def flatten(l):
    return [item for sublist in l for item in sublist]


def get_related_wordnet_lemmas(grapheme):
    '''
    Return *all* lemmas for *all* synsets within distance-1 of *all* of the grapheme's synsets
    Don't need to muck around with cases, because WordNet is smart enough to handle that itself
    '''
    if not wn.synsets(grapheme):
        return []
    
    # These are all of the non-antonym non-POS synset relationships recognized by WordNet
    relationship_types = [
        'hypernyms','instance_hypernyms','hyponyms','instance_hyponyms', \
        'member_holonyms','substance_holonyms','part_holonyms','member_meronyms', \
        'substance_meronyms','part_meronyms','topic_domains','region_domains', \
        'usage_domains','attributes','entailments','causes','also_sees','verb_groups','similar_tos']
    
    lemmas = set()
    for synset in wn.synsets(grapheme):
        # distance-0 lemmas
        lemmas.update(synset.lemma_names())
        # distance-1 lemmas
        for relationship in relationship_types:
            related_synsets = getattr(synset, relationship)()
            lemmas.update(flatten([s.lemma_names() for s in related_synsets]))
        
    # Convert from unicode with str, and return the results as a list
    return list(map(str, lemmas))


def get_word2vec_neighbors(grapheme, word2vec_model):
    for g in alternative_grapheme_capitalizations(grapheme):
        if g in word2vec_model.vocab:
            return list(zip(*word2vec_model.most_similar(positive=[g], topn=MAX_NEIGHBORS))[0])
    else:
        raise 'This code path should NEVER execute, something has gone HORRIBLY wrong'


def get_shortest_lemma(grapheme, lemmatizer=WordNetLemmatizer(), stemmer=PorterStemmer()):
    '''
    Need to check all possible parts of parts of speech to make sure that we identify the *shortest* lemma
    If don't manually check all parts of speech, it defaults to using the lemmas of the first synset, which may
    not be what we want.

    The parts of speech are:
      n : NOUN
      v : VERB
      a : ADJECTIVE
      s : ADJECTIVE SATELLITE
      r : ADVERB

    Note: be sure to predefine/pass in the lemmatizer in advance, so that it doesn't need to be recreated on each run
    '''
    
    shortest_lemma = grapheme

    # First attempt to trim using lemmatizer
    for pos in ['n','v','a','s','r']:
        lemma = lemmatizer.lemmatize(grapheme, pos)
        if len(lemma) < len(shortest_lemma):
            shortest_lemma = lemma

    # Next attempt to trim using stemmer; further trim down whatever was produced by the lemmatizer
    # Stems are not always valid words, so check that the result is present in WordNet
    stem = stemmer.stem(shortest_lemma)
    if len(wn.synsets(stem)) >= 1 and len(stem) < len(shortest_lemma):
        shortest_lemma = stem

    return shortest_lemma


def get_semantic_neighbor_graphemes(grapheme, word2vec_model):
    wordnet_neighbors = get_related_wordnet_lemmas(grapheme)

    # DO NOT like how this 'word2vec_model' parameter is being passed through
    word2vec_neighbors = get_word2vec_neighbors(grapheme, word2vec_model)

    # word2vec sometimes returns funky unicode characters like umlouts, so make sure to catch/discard these before moving on
    word2vec_neighbors_clean = []
    for g in word2vec_neighbors:
        try:
            word2vec_neighbors_clean.append(str(g))
        except:
            pass

    # Keep it simple to start: Downcase --> Lemmatize --> Set
    # Make sure to consider the lemmas for ALL possible synsets of a given word, and pick the shortest
    wnl = WordNetLemmatizer()
    semantic_neighbor_graphemes = set(map(lambda g: get_shortest_lemma(g.lower(), wnl), [grapheme]+wordnet_neighbors+word2vec_neighbors_clean))
    return semantic_neighbor_graphemes


def get_portmanteaus(words1_neighbors, words2_neighbors, grapheme_to_word_dict):
    # use a set to avoid redundancy in case the same word appears in both sets
    portmanteau_set = set()
    for neighbor1 in words1_neighbors:
        for neighbor2 in words2_neighbors:
            # if the words are identical, as sometimes happens, skip it
            if neighbor1.grapheme == neighbor2.grapheme:
                continue
            # generate both orderings
            portmanteau, status, message = Portmanteau.get_portmanteau(neighbor1, neighbor2, grapheme_to_word_dict)
            if status == 0:
                portmanteau_set.add(portmanteau)
            portmanteau, status, message = Portmanteau.get_portmanteau(neighbor2, neighbor1, grapheme_to_word_dict)
            if status == 0:
                portmanteau_set.add(portmanteau)
    
    portmanteau_list = list(portmanteau_set)

    # Order according to quality
    portmanteau_list.sort(key=lambda x: x.ordering_criterion())

    return portmanteau_list


def get_rhymes(words1_neighbors, words2_neighbors, grapheme_to_word_dict):
    # use a set to avoid redundancy in case the same word appears in both sets
    rhyme_set = set()
    for neighbor1 in words1_neighbors:
        for neighbor2 in words2_neighbors:
            # if the words are identical, as sometimes happens, skip it
            if neighbor1.grapheme == neighbor2.grapheme:
                continue
            # generate ONE orderings - if word order needs to be flipped for quality reasons, that's handled within the 'get_rhyme' function
            rhyme, status, message = Rhyme.get_rhyme(neighbor1, neighbor2, grapheme_to_word_dict)
            if status == 0:
                rhyme_set.add(rhyme)

    rhyme_list = list(rhyme_set)

    # Order according to quality
    rhyme_list.sort(key=lambda x: x.ordering_criterion())

    return rhyme_list