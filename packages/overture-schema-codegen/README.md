# overture-schema-codegen

Code generation tools for Overture Maps schemas.

This package provides tools for generating code from Pydantic models, with initial focus on Spark-compatible Scala code generation.

## Features

- Generate Spark-compatible Scala case classes from Pydantic models
- Support for discriminated unions as sealed traits
- Optimized type mappings for Spark Dataset operations
- Custom encoder generation for complex types
- Companion object methods for DataFrame interop

## Usage

```python
from overture.schema.codegen.spark import SparkScalaCodeGenerator

# Generate Scala code from Pydantic models
generator = SparkScalaCodeGenerator(package="com.example")
scala_code = generator.generate_case_class(MyModel)
```

See the `spark_generator.py` file in the root directory for detailed examples and documentation.
