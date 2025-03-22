import anki.collection
from anki.collection import Collection
from pprint import pprint
import json

col = Collection("/Users/leofidjeland/Library/Application Support/Anki2/Leo/collection.anki2")
noteIds = col.find_notes("deck:\"ཚིག་གསར་\"")

def getNoteInfo(note, print):

    if isinstance(note, int):
        note = col.get_note(note)

    items = note.items()
    tibetan = ""
    tense = ""

    for (name, value) in items:
        if name == 'Tibetan':
            tibetan = value
        if name == 'Tense':
            tense = value
        # note[name] = value + " new"

    

    if len(tense) > 0:
        # pprint(tense)
        if(tense[:5]) == '<div>' and tense[-6:] == '</div>':
            note['Tense'] = tense[5:-6]
            col.update_note(note)
            pprint("Updated " + tibetan)
            # pprint(tense)
            # pprint(tense[5:-6]);


    # if sentence.find(tibetan) != -1:#found the whole string
    #     if sentence[sentence.find(tibetan) - 1] == '>':
    #         pprint("skipped " + tibetan)
    #     else:
    #         sentence = sentence.replace(tibetan,"<span style=\"color: rgb(170, 0, 127);\">" + tibetan + "</span>")
    #         note['Example Sentence Tibetan'] = sentence
    #         col.update_note(note)
    #         pprint("updated " + tibetan)
    # elif sentence.find(tibetan[:-1]) != -1:#found the string minute last char
    #     if sentence[sentence.find(tibetan[:-1]) - 1] == '>':
    #         pprint("skipped " + tibetan)
    #     else:
    #         sentence = sentence.replace(tibetan[:-1],"<span style=\"color: rgb(170, 0, 127);\">" + tibetan[:-1] + "</span>")
    #         note['Example Sentence Tibetan'] = sentence
    #         col.update_note(note)
    #         pprint("updated " + tibetan)
    # elif tibetan[-3:] == '་པ་' and sentence.find(tibetan[:-3]) != -1:
    #     if sentence[sentence.find(tibetan[:-3]) - 1] == '>':
    #         pprint("skipped " + tibetan)
    #     else:
    #         sentence = sentence.replace(tibetan[:-3],"<span style=\"color: rgb(170, 0, 127);\">" + tibetan[:-3] + "</span>")
    #         note['Example Sentence Tibetan'] = sentence
    #         col.update_note(note)
    #         pprint("updated " + tibetan)
    
    # pprint(tibetan)
    # pprint(sentence)

output = []

count = 0

for noteId in noteIds:
    output.append(getNoteInfo(noteId, False))
    count += 1
    # if count > 10:
        # break

# print(len(output))

col.close()