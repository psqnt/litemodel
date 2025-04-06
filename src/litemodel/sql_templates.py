CREATE_TABLE_TEMPLATE = """CREATE TABLE {{table}} (
        id INTEGER PRIMARY KEY,
        {%- for name, type in fields.items() %}
        {{name}} {{type.sqlite_type}}{{not_null.get(name,'')}}{% if not loop.last -%},{%- endif -%}
        {% endfor %}
    )"""

INSERT_TEMPLATE = """INSERT INTO {{table}} 
        (
        {%- for col_name in fields %}
        {{col_name}}{% if not loop.last -%},{%- endif -%}
        {% endfor %}
        )
    VALUES
        ({%- for col_name in fields %}?{% if not loop.last -%},{%- endif -%}{% endfor %})
"""

UPDATE_TEMPLATE = """UPDATE {{table}}
    SET 
        {% for field in fields %}
        {{field}} = ?{% if not loop.last -%},{%- endif -%}
        {% endfor %}
    WHERE
        {{where}} = ?
"""

FIND_BY_TEMPLATE = """SELECT * FROM {{table}} WHERE {% for field in fields %}{{field}} = ?{% if not loop.last %} AND {% endif %}{% endfor %}"""

DELETE_BY_TEMPLATE = """DELETE FROM {{table}} WHERE {{field}} = ?"""
