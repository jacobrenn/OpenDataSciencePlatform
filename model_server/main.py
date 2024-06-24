from fastapi.responses import RedirectResponse
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import numpy as np
import subprocess
import mlflow

# Global variables for model flavors
# NOTE: "transformer" should also be supported here, but there are unknowns with running inference directly
ALLOWED_MODEL_FLAVORS = [
    'pyfunc',
    'sklearn'
]
PYFUNC_FLAVOR = ALLOWED_MODEL_FLAVORS[0]
SKLEARN_FLAVOR = ALLOWED_MODEL_FLAVORS[1]

# Global variables for prediction functions
ALLOWED_PREDICT_FUNCTIONS = [
    'predict',
    'predict_proba'
]
PREDICT = ALLOWED_PREDICT_FUNCTIONS[0]
PREDICT_PROBA = ALLOWED_PREDICT_FUNCTIONS[1]

# Global variable for already loaded models
LOADED_MODELS = dict()

class PredictRequest(BaseModel):
    data : list
    predict_function : str = 'predict'
    model_flavor : str = 'pyfunc'
    dtype : str = None
    params : dict = None

# Load_model function that allows to load model from either alias or version
def load_model(model_name, model_flavor, model_version = None, model_alias = None):
    f"""
    Load a model from the MLFlow server

    Parameters
    ----------
    model_name : str
        The name of the model
    model_flavor : str
        The flavor of the model, must be one of {ALLOWED_MODEL_FLAVORS}
    model_version : int or None (default None)
        The version of the model
    model_alias : str or None (default None)
        The alias of the model, without the `@` character

    Notes
    -----
    - One of either `model_version` or `model_alias` must be provided

    Returns
    -------
    model : mlflow Model
        The model, in the flavor specified

    Raises
    ------
    - MlflowException, when the model cannot be loaded
    """
    
    if not (model_version or model_alias):
        raise ValueError('Model version or model alias must be provided')
    
    if model_flavor not in ALLOWED_MODEL_FLAVORS:
        raise ValueError(f'Only "pyfunc" and "sklearn" model flavors supported, got {model_flavor}')
    
    try:
        
        if model_version:
            model_uri = f'models:/{model_name}/{model_version}'
        elif model_alias:
            model_uri = f'models:/{model_name}@{model_alias}'

        # Install dependencies for the model
        subprocess.run(
            [
                'pip',
                'install',
                '-r',
                mlflow.pyfunc.get_model_dependencies(model_uri)
            ]
        )
        
        # Load the model if it is requested to be a pyfunc model
        if model_flavor == PYFUNC_FLAVOR:
            model = mlflow.pyfunc.load_model(model_uri)

        # Load the model if it is requested to be a sklearn model
        elif model_flavor == SKLEARN_FLAVOR:
            model = mlflow.sklearn.load_model(model_uri)
        
        return model
    
    except Exception as e:
        raise mlflow.MlflowException('Could not load model')

# Predict_model function that runs prediction
def predict_model(model, to_predict, model_flavor, predict_function, params):

    if predict_function == 'predict':
        try:
            if model_flavor != 'sklearn':
                results = model.predict(to_predict, params = params)
            else:
                results = model.predict(to_predict)
        except Exception:
            try:
                results = model.predict(to_predict.reshape(-1, 1))
            except Exception:
                raise ValueError('There was an issue running `predict`')
    
    elif predict_function == 'predict_proba':
        try:
            results = model.predict_proba(to_predict)
        except Exception:
            try:
                results = model.predict_proba(to_predict.reshape(-1, 1))
            except Exception:
                raise ValueError('There was an issue running `predict_proba`')
    
    else:
        raise ValueError('Only `predict` and `predict_proba` are supported predict functions')
    
    if isinstance(results, np.ndarray):
        results = results.tolist()

    return {
        'prediction' : results
    }

# Initialize the app
app = FastAPI()

# Redirect to docs for the landing page
@app.get('/', include_in_schema = False)
def redirect_docs():
    return RedirectResponse(url = '/inference/docs')

@app.get('/load_model/{model_name}/{model_flavor}/{model_version_or_alias}')
def setup_model(model_name : str, model_flavor : str, model_version_or_alias : str | int):
    
    # Try to load the model
    try:
        model = load_model(model_name, model_flavor, model_version_or_alias)
    except Exception:
        try:
            model = load_model(model_name, model_flavor, model_alias = model_version_or_alias)
        except Exception:
            raise HTTPException(404, 'Model with that combination of name, flavor, and version or alias not found')
    
    # Place the model in the right location in the model in-memory storage
    if not LOADED_MODELS.get(model_name):
        LOADED_MODELS[model_name] = {
            model_flavor : {
                model_version_or_alias : model
            }
        }
    elif not LOADED_MODELS[model_name].get(model_flavor):
        LOADED_MODELS[model_name][model_flavor] = {
            model_version_or_alias : model
        }
    elif not LOADED_MODELS[model_name][model_flavor].get(model_version_or_alias):
        LOADED_MODELS[model_name][model_flavor][model_version_or_alias] = model
    
    return {
        'success' : True
    }

# See loaded models
@app.get('/loaded_models')
def list_models():
    if LOADED_MODELS == {}:
        return []
    else:
        to_return = []
        for model_name in LOADED_MODELS.keys():
            for model_flavor in LOADED_MODELS[model_name]:
                for model_version in LOADED_MODELS[model_name][model_flavor].keys():
                    to_return.append(f'{model_name}_{model_flavor}_{model_version}')
        return to_return

# Delete a loaded model
@app.delete('/{model_name}/{model_flavor}/{model_version_or_alias}')
def unload_model(model_name : str, model_flavor : str, model_version_or_alias : str | int):
    try:
        del LOADED_MODELS[model_name][model_flavor][model_version_or_alias]
        return {
            'success' : True
        }
    except Exception:
        raise HTTPException(404, 'Model not found')
    
# Predict using model version
@app.post('/{model_name}/version/{model_version}')
def predict_version(model_name : str, model_version : str | int, body : PredictRequest):

    # Try to load the model, assuming it has been loaded before
    try:
        model = LOADED_MODELS[model_name][body.model_flavor][model_version]
    except Exception as e:

        # Model has not been loaded before
        model = load_model(model_name, body.model_flavor, model_version)
          
        # Place the model in the right location in the model in-memory storage
        if not LOADED_MODELS.get(model_name):
            LOADED_MODELS[model_name] = {
                body.model_flavor : {
                    model_version : model
                }
            }
        elif not LOADED_MODELS[model_name].get(body.model_flavor):
            LOADED_MODELS[model_name][body.model_flavor] = {
                model_version : model
            }
        elif not LOADED_MODELS[model_name][body.model_flavor].get(model_version):
            LOADED_MODELS[model_name][body.model_flavor][model_version] = model
    
    # Grab the data to predict on from the input body
    try:
        to_predict = np.array(body.data)
        if body.dtype:
            to_predict = to_predict.astype(body.dtype)
    except Exception:
        raise HTTPException(
            400,
            'Data malformed and could not be processed'
        )
    
    try:
        return predict_model(
            model,
            to_predict,
            body.model_flavor,
            body.predict_function,
            body.params
        )
    except Exception as e:
        raise HTTPException(400, e.message)

# Predict using model alias
@app.post('/{model_name}/alias/{model_alias}')
def predict_alias(model_name : str, model_alias : str | int, body : PredictRequest):

    # Try to load the model, assuming it hasn't been loaded before
    try:
        model = LOADED_MODELS[model_name][body.model_flavor][model_alias]
    except Exception as e:

        # Model has not been loaded before
        model = load_model(model_name, body.model_flavor, model_alias = model_alias)

        # Place the model in the right location in the model in-memory storage
        if not LOADED_MODELS.get(model_name):
            LOADED_MODELS[model_name] = {
                body.model_flavor : {
                    model_alias : model
                }
            }
        elif not LOADED_MODELS[model_name].get(body.model_flavor):
            LOADED_MODELS[model_name][body.model_flavor] = {
                model_alias : model
            }
        elif not LOADED_MODELS[model_name][body.model_flavor].get(model_alias):
            LOADED_MODELS[model_name][body.model_flavor][model_alias] = model

    # Grab the data to predict on from the input body
    try:
        to_predict = np.array(body.data)
        if body.dtype:
            to_predict = to_predict.astype(body.dtype)
    except Exception:
        raise HTTPException(
            400,
            'Data malformed and could not be processed'
        )
    
    # Run prediction
    try:
        return predict_model(
            model,
            to_predict,
            body.model_flavor,
            body.predict_function,
            body.params
        )
    except Exception as e:
        raise HTTPException(400, e.message)