# LiteModel

## Install
```
pip install litemodel
```

## Usage

### Sync
```
# import Model
from litemodel.core import Model


# Define the Model
class Note(Model):
    title: str
    text: Optional[str]
    archived: bool = False

# Create the table in sqlite
Note.create_table()

# Create an instance
note = Note(title="Test", text="Just Testing")
note.save()

# Get the note
note = Note.find_by("title", "Test")

# Update the note
note.text = "Updating the note"
note.save()
```
### Async
```
# import Model
from litemodel.async_core import Model


# Define the Model
class Note(Model):
    title: str
    text: Optional[str]
    archived: bool = False

# Create the table in sqlite
await Note.create_table()

# Create an instance
note = Note(title="Test", text="Just Testing")
await note.save()

# Get the note
note = await Note.find_by("title", "Test")

# Update the note
note.text = "Updating the note"
await note.save()
```

