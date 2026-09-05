# Данные

`data/titanic_train.csv` — детерминированный Titanic-shaped dataset на 891 строку с классической схемой:

```text
PassengerId, Survived, Pclass, Name, Sex, Age,
SibSp, Parch, Ticket, Fare, Cabin, Embarked
```

Dataset генерируется `data/generate_dataset.py` и включен в архив, поэтому проект работает офлайн.

## Что использует модель

Raw features:

```text
Pclass, Sex, Age, SibSp, Parch, Fare, Embarked
```

Derived features внутри pipeline:

```text
FamilySize    = SibSp + Parch + 1
IsAlone       = FamilySize == 1
IsChild       = Age < 15
FarePerPerson = Fare / FamilySize
```

Не используются:

- `PassengerId` — ID;
- `Name` — high-cardinality string;
- `Ticket` — high-cardinality string;
- `Cabin` — high-cardinality field с большим числом missing values;
- `Survived` — target.

## Качество

Детерминированный holdout (`random_state=42`):

```text
accuracy = 0.8545
ROC-AUC  = 0.9061
```

```bash
make evaluate
```

## Missing values

`Age` и `Embarked` намеренно содержат пропуски. Они обрабатываются внутри sklearn pipeline через `SimpleImputer`.

В исходном monitoring-проекте реальный Titanic CSV скачивался из интернета. Здесь набор локальный ради полностью воспроизводимой лекции; schema совместима с классическим Titanic train.csv.
