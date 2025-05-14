import anki.collection
from anki.collection import Collection
from pprint import pprint
import json

col = Collection("/Users/leofidjeland/Library/Application Support/Anki2/Leo/collection.anki2")
noteIds = col.find_notes("note:\"Tibetan Vocab Literary\"")

def getNoteInfo(note, print):

    if isinstance(note, int):
        note = col.get_note(note)

    items = note.items()
    sound = ""

    for (name, value) in items:
        if name == 'Sound':
            sound = value

    # pprint(sentence)

    if sound.find("<br>") != -1:#found the whole string
        sound = sound.replace("<br>","")
        note['Sound'] = sound
        col.update_note(note)
        # pprint("updated " + tibetan)
    
    # pprint(tibetan)
    # pprint(sentence)

output = []

count = 0

for noteId in noteIds:
    output.append(getNoteInfo(noteId, False))
    count += 1
    print(count)
    # if count > 0:
    #     break

print(len(output))

col.close()