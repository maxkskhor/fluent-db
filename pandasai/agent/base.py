import traceback
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Union, Generator

import pandas as pd

from pandasai.core.code_execution.code_executor import CodeExecutor
from pandasai.core.code_generation.base import CodeGenerator
from pandasai.core.prompts import (
    get_chat_prompt_for_sql,
    get_correct_error_prompt_for_sql,
    get_correct_output_type_error_prompt,
)
from pandasai.core.response import ErrorResponse, ResponseParser
from pandasai.dataframe.base import DataFrame
from pandasai.dataframe.virtual_dataframe import VirtualDataFrame
from pandasai.exceptions import (
    InvalidLLMOutputType,
    MissingVectorStoreError,
)
from pandasai.sandbox import Sandbox
from pandasai.vectorstores.vectorstore import VectorStore
from .state import AgentState
from ..config import Config
from ..core.response import BaseResponse
from ..data_loader.duck_db_connection_manager import DuckDBConnectionManager
from ..query_builders.base_query_builder import BaseQueryBuilder
from ..query_builders.sql_parser import SQLParser


class Stage(Enum):
    CODE_GENERATION = 'code_generation'
    CODE_EXECUTION_FAILURE = 'code_execution_failure'
    CODE_REGENERATION = 'code_regeneration'
    FINAL_ERROR = 'final_error'
    FINAL_RESULT = 'final_result'


@dataclass
class StreamResponse:
    stage: Stage
    content: BaseResponse | str
    metadata: dict = field(default_factory=dict)


class Agent:
    """
    Base Agent class to improve the conversational experience in PandaAI
    """

    def __init__(
        self,
        dfs: Union[
            Union[DataFrame, VirtualDataFrame], List[Union[DataFrame, VirtualDataFrame]]
        ],
        config: Optional[Union[Config, dict]] = None,
        memory_size: Optional[int] = 10,
        vectorstore: Optional[VectorStore] = None,
        description: str = None,
        sandbox: Sandbox = None,
    ):
        """
        Args:
            dfs (Union[Union[DataFrame, VirtualDataFrame], List[Union[DataFrame, VirtualDataFrame]]]): The dataframe(s) to be used for the conversation.
            config (Optional[Union[Config, dict]]): The configuration for the agent.
            memory_size (Optional[int]): The size of the memory.
            vectorstore (Optional[VectorStore]): The vectorstore to be used for the conversation.
            description (str): The description of the agent.
        """

        # Deprecation warnings
        if config is not None:
            warnings.warn(
                "The 'config' parameter is deprecated and will be removed in a future version. "
                "Please use the global configuration instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        if isinstance(dfs, list):
            sources = [df.schema.source or df._loader.source for df in dfs]
            if not BaseQueryBuilder.check_compatible_sources(sources):
                raise ValueError(
                    f"The sources of these datasets: {dfs} are not compatibles"
                )

        self.description = description
        self._state = AgentState()
        self._state.initialize(dfs, config, memory_size, vectorstore, description)

        self._code_generator = CodeGenerator(self._state)
        self._response_parser = ResponseParser()
        self._sandbox = sandbox

    def chat(self, query: str, output_type: Optional[str] = None) -> BaseResponse:
        """
        Start a new chat interaction with the assistant on Dataframe.
        """
        self.start_new_conversation()
        result_stream = list(self._process_query(query, output_type))
        return result_stream[-1].content

    def follow_up(self, query: str, output_type: Optional[str] = None) -> BaseResponse:
        """
        Continue the existing chat interaction with the assistant on Dataframe.
        """
        result_stream = list(self._process_query(query, output_type))
        return result_stream[-1].content

    def chat_with_stream(self, query: str, output_type: Optional[str] = None):
        self.start_new_conversation()
        yield from self._process_query(query, output_type)

    def follow_up_with_stream(self, query: str, output_type: Optional[str] = None):
        yield from self._process_query(query, output_type)

    def generate_code(self) -> str:
        """Generate code using the LLM."""

        self._state.logger.log("Generating new code...")
        prompt = get_chat_prompt_for_sql(self._state)
        self._state.last_prompt_used = prompt
        code = self._code_generator.generate_code(prompt)

        return code

    def execute_code(self, code: str) -> dict:
        """Execute the generated code."""
        self._state.logger.log(f"Executing code:\n{code}")

        code_executor = CodeExecutor(self._state.config)
        code_executor.add_to_env("execute_sql_query", self._execute_sql_query)

        if self._sandbox:
            return self._sandbox.execute(code, code_executor.environment)

        return code_executor.execute_and_return_result(code)

    def generate_code_with_retries(self) -> Any:
        """Execute the code with retry logic."""
        max_retries = self._state.config.max_retries
        attempts = 0
        try:
            code = self.generate_code()
            yield StreamResponse(Stage.CODE_GENERATION, code)

        except Exception as e:
            exception = e
            while attempts <= max_retries:
                try:
                    yield from self._regenerate_code_after_error(self._state.last_code_generated, exception)
                    break
                except Exception as e:
                    exception = e
                    attempts += 1
                    if attempts > max_retries:
                        self._state.logger.error(f"Maximum retry attempts exceeded. Last error: {e}")
                        raise
                    self._state.logger.warning(
                        f"Retrying Code Generation ({attempts}/{max_retries})..."
                    )

    def execute_with_retries(self) -> Generator[StreamResponse, None, None]:
        """Execute the code with retry logic."""
        max_retries = self._state.config.max_retries
        attempts = 0

        while attempts <= max_retries:
            try:
                result = self.execute_code(self._state.last_code_cleaned)
                yield StreamResponse(
                    Stage.FINAL_RESULT,
                    self._response_parser.parse(result, self._state.last_code_cleaned)
                )
                break
            except Exception as e:
                attempts += 1
                if attempts > max_retries:
                    self._state.logger.error(f"Max retries reached. Error: {e}")
                    raise
                self._state.logger.warning(f"Retrying execution ({attempts}/{max_retries})...")

                # update last_code_cleaned
                yield from self._regenerate_code_after_error(self._state.last_code_cleaned, e)

    def _process_query(self, query: str, output_type: Optional[str] = None) -> Generator[StreamResponse, None, None]:
        """Process a user query and return the result."""
        self._state.logger.log(f"Question: {query}")
        self._state.logger.log(f"Running PandaAI with {self._state.config.llm.type} LLM...")
        self._state.output_type = output_type
        self._state.assign_prompt_id()
        self._state.memory.add(str(query), is_user=True)

        try:
            # Generate code; Update last_code_generated and last_code_cleaned
            yield from self.generate_code_with_retries()

            # Execute code with retries
            yield from self.execute_with_retries()

            self._state.logger.log("Response generated successfully.")
            # Generate and return the final response

        except Exception as e:
            self._state.logger.log(f"Exception: {e}")
            yield StreamResponse(Stage.FINAL_ERROR, self._handle_exception(self._state.last_code_cleaned))

    def _regenerate_code_after_error(self, code: str, error: Exception) -> Generator[StreamResponse, None, None]:
        """Generate a new code snippet based on the error."""
        error_trace = traceback.format_exc()
        self._state.logger.log(f"Execution failed with error: {error_trace}")
        yield StreamResponse(Stage.CODE_EXECUTION_FAILURE, error_trace)

        if isinstance(error, InvalidLLMOutputType):
            prompt = get_correct_output_type_error_prompt(
                self._state, code, error_trace
            )
        else:
            prompt = get_correct_error_prompt_for_sql(self._state, code, error_trace)

        code = self._code_generator.generate_code(prompt)
        yield StreamResponse(Stage.CODE_REGENERATION, code)

    def _handle_exception(self, code: str) -> ErrorResponse:
        """Handle exceptions and return an error message."""
        error_message = traceback.format_exc()
        self._state.logger.log(f"Processing failed with error: {error_message}")

        return ErrorResponse(last_code_executed=code, error=error_message)

    def train(
        self,
        queries: Optional[List[str]] = None,
        codes: Optional[List[str]] = None,
        docs: Optional[List[str]] = None,
    ) -> None:
        """
        Trains the context to be passed to model
        Args:
            queries (Optional[str], optional): user
            codes (Optional[str], optional): generated code
            docs (Optional[List[str]], optional): additional docs
        Raises:
            ImportError: if the default vector db lib is not installed, it raises an error
        """
        if self._state.vectorstore is None:
            raise MissingVectorStoreError(
                "No vector store provided. Please provide a vector store to train the agent."
            )

        if (queries and not codes) or (not queries and codes):
            raise ValueError(
                "If either queries or codes are provided, both must be provided."
            )

        if docs is not None:
            self._state.vectorstore.add_docs(docs)

        if queries and codes:
            self._state.vectorstore.add_question_answer(queries, codes)

        self._state.logger.log("Agent successfully trained on the data")

    def clear_memory(self):
        """
        Clears the memory
        """
        self._state.memory.clear()

    def add_message(self, message, is_user=False):
        """
        Add a message to the memory. This is useful when you want to add a message
        to the memory without calling the chat function (for example, when you
        need to add a message from the agent).
        """
        self._state.memory.add(message, is_user=is_user)

    def start_new_conversation(self):
        """
        Clears the previous conversation
        """
        self.clear_memory()


    def _execute_sql_query(self, query: str) -> pd.DataFrame:
        """
        Executes an SQL query on registered DataFrames.

        Args:
            query (str): The SQL query to execute.

        Returns:
            pd.DataFrame: The result of the SQL query as a pandas DataFrame.
        """
        if not self._state.dfs:
            raise ValueError("No DataFrames available to register for query execution.")

        db_manager = DuckDBConnectionManager()

        table_mapping = {}
        df_executor = None

        for df in self._state.dfs:
            if hasattr(df, "query_builder"):
                # df is a valid dataset with query builder, loader and execute_sql_query method
                table_mapping[df.schema.name] = df.query_builder._get_table_expression()
                df_executor = df.execute_sql_query
            else:
                # dataset created from loading a csv, no query builder available
                db_manager.register(df.schema.name, df)

        final_query = SQLParser.replace_table_and_column_names(query, table_mapping)

        if not df_executor:
            return db_manager.sql(final_query).df()
        else:
            return df_executor(final_query)
