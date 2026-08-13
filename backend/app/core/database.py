from pprint import pformat

from sqlalchemy.ext.declarative import (
    declarative_base,
    declared_attr,
)

from app.core.utils.nameing import convert_class_name


class CustomBase:
    @declared_attr
    def __tablename__(self):
        return convert_class_name(self.__name__)

    def __repr__(self):
        return pformat(
            {
                k: v
                for k, v in self.__dict__.items()
                if not k.startswith("_")
            }
        )


Base = declarative_base(cls=CustomBase)
