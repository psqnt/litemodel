# LiteModel

## Install
```
pip install litemodel
```

## Usage

### Sync
```python
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
```python
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

## Example Project
I used this to build a CLI note app you can see here:
https://github.com/psqnt/notes

look in the `__main__.py` file for some queries / instance creation and look in `db.py` for how to handle database creation / connection

## Configuration
You can set some environment variables to control behavior

*set where litemodel will look for your database*
```
export DATABASE_PATH=/path/to/my/db/sqlite.db
```

*set to debug mode*
```
export LITEMODEL_DEBUG=True
```

## Note
This was written fairly quickly and is lacking some functionality that I hopefully can get to soon. However, its a very small project so should be easy to update if you want to fork. Also its easily extensible to make better queries when needed

